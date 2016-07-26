#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
import isodate
from io import BytesIO
from datetime import datetime

from zope import component

from zope.event import notify

from zope.catalog.interfaces import ICatalog

from zope.intid.interfaces import IIntIds

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.store import MessageFactory as _

from nti.app.store.utils import to_boolean
from nti.app.store.utils import parse_datetime
from nti.app.store.utils import AbstractPostView
from nti.app.store.utils import is_valid_pve_int

from nti.app.store.views import StorePathAdapter

from nti.common.maps import CaseInsensitiveDict

from nti.dataserver import authorization as nauth

from nti.dataserver.metadata_index import IX_CREATOR
from nti.dataserver.metadata_index import IX_MIMETYPE
from nti.dataserver.metadata_index import CATALOG_NAME as METADATA_CATALOG_NAME

from nti.dataserver.users import User

from nti.externalization import integer_strings

from nti.store.interfaces import PA_STATE_SUCCESS
from nti.store.interfaces import PAYMENT_PROCESSORS

from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IPurchaseHistory
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import PurchaseAttemptSuccessful

from nti.store.store import get_gift_code
from nti.store.store import get_gift_registry
from nti.store.store import get_invitation_code
from nti.store.store import get_purchase_by_code
from nti.store.store import get_purchase_attempt
from nti.store.store import delete_purchase_history
from nti.store.store import remove_purchase_attempt
from nti.store.store import get_gift_purchase_history

from nti.store.purchase_attempt import create_purchase_attempt

from nti.store.purchase_order import create_purchase_item
from nti.store.purchase_order import create_purchase_order

from nti.store.purchasable import get_purchasable

from nti.store.utils import PURCHASE_ATTEMPT_MIME_TYPES

from nti.zodb import is_broken

def _tx_string(s):
	if s is not None and isinstance(s, unicode):
		s = s.encode('utf-8')
	return s

@view_config(name="GetUsersPurchaseHistory")
@view_config(name="get_users_purchase_history")
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   context=StorePathAdapter,
			   request_method='GET')
class GetUsersPurchaseHistoryView(AbstractAuthenticatedView):

	def __call__(self):
		request = self.request
		params = CaseInsensitiveDict(request.params)
		purchasable = 	 params.get('ntiid') \
					  or params.get('purchasable') \
					  or params.get('purchasableID')
		if purchasable and get_purchasable(purchasable) is None:
			raise hexc.HTTPUnprocessableEntity(detail=_('Purchasable not found.'))

		all_failed = to_boolean(params.get('failed'))
		all_succeeded = to_boolean(params.get('succeeded'))

		mime_types = PURCHASE_ATTEMPT_MIME_TYPES
		catalog = component.getUtility(ICatalog, METADATA_CATALOG_NAME)
		intids_purchases = catalog[IX_MIMETYPE].apply({'any_of': mime_types})

		usernames = params.get('usernames') or params.get('username')
		if usernames:
			usernames = [x.lower() for x in usernames.split(",")]
			creator_intids = catalog[IX_CREATOR].apply({'any_of': usernames})
			intids_purchases = catalog.family.IF.intersection(intids_purchases,
															  creator_intids)

		stream = BytesIO()
		writer = csv.writer(stream)
		response = request.response
		response.content_encoding = str('identity')
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str('attachment; filename="purchases.csv"')

		header = ["username", 'name', 'email', 'transaction', 'date', 'amount', 'status']
		writer.writerow(header)

		intids = component.getUtility(IIntIds)
		for uid in intids_purchases:
			purchase = intids.queryObject(uid)
			if is_broken(purchase, uid) or not IPurchaseAttempt.providedBy(purchase):
				continue

			if purchasable and purchasable not in purchase.Items:
				continue

			if  	(all_succeeded and not purchase.has_succeeded()) \
				or	(all_failed and not purchase.has_failed()):
				continue

			status = purchase.State
			code = get_invitation_code(purchase)
			date = isodate.date_isoformat(datetime.fromtimestamp(purchase.StartTime))
			amount = getattr(purchase.Pricing, 'TotalPurchasePrice', None) or u''

			username = getattr(purchase.creator, 'username', purchase.creator).lower()
			profile = purchase.profile
			email = getattr(profile, 'email', None) or u''
			name = getattr(profile, 'realname', None) or username

			row_data = [ username, name, email, code, date, amount, status ]
			writer.writerow([ _tx_string(x) for x in row_data])

		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

@view_config(name="GetUsersGiftHistory")
@view_config(name="get_users_gift_history")
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   context=StorePathAdapter,
			   request_method='GET')
class GetUsersGiftHistoryView(AbstractAuthenticatedView):

	def __call__(self):
		request = self.request
		params = CaseInsensitiveDict(request.params)
		usernames = params.get('username') or params.get('usernames')
		if usernames:
			usernames = set(usernames.split(","))

		all_failed = to_boolean(params.get('failed'))
		all_succeeded = to_boolean(params.get('succeeded'))

		end_time = parse_datetime(params.get('endTime', None))
		start_time = parse_datetime(params.get('startTime', None))

		stream = BytesIO()
		writer = csv.writer(stream)
		response = request.response
		response.content_encoding = str('identity')
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str('attachment; filename="gifts.csv"')

		header = ["transaction", "from", 'sender', 'to', 'receiver', 'date',
				  'amount', 'status']
		writer.writerow(header)

		registry = get_gift_registry()
		for username in registry.keys():
			if usernames and username not in usernames:
				continue
			purchases = get_gift_purchase_history(username, start_time=start_time,
												  end_time=end_time)
			if all_succeeded:
				purchases = [p for p in purchases if p.has_succeeded()]
			elif all_failed:
				purchases = [p for p in purchases if p.has_failed()]

			for p in purchases:
				started = isodate.date_isoformat(datetime.fromtimestamp(p.StartTime))
				amount = getattr(p.Pricing, 'TotalPurchasePrice', None) or u''
				row_data = [get_gift_code(p),
							username, p.SenderName,
							p.Receiver, p.ReceiverName,
							started,
							amount,
							p.State]
				writer.writerow([ _tx_string(x) for x in row_data])

		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

# post views

_BasePostStoreView = AbstractPostView  # alias

@view_config(name="DeletePurchaseAttempt")
@view_config(name="delete_purchase_attempt")
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   context=StorePathAdapter,
			   request_method='POST')
class DeletePurchaseAttemptView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		purchase_id = 	 values.get('ntiid') \
					  or values.get('purchase') \
					  or values.get('purchaseId')
		if not purchase_id:
			msg = _("Must specify a valid purchase attempt id.")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = get_purchase_attempt(purchase_id)
		if not purchase:
			msg = _('Purchase attempt not found.')
			raise hexc.HTTPNotFound(msg)

		if remove_purchase_attempt(purchase, purchase.creator):
			logger.info("Purchase attempt '%s' has been deleted")
		return hexc.HTTPNoContent()

@view_config(name="DeletePurchaseHistory")
@view_config(name="delete_purchase_history")
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   context=StorePathAdapter,
			   request_method='POST')
class DeletePurchaseHistoryView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		username = values.get('username')
		if not username:
			msg = _("Must specify a valid username.")
			raise hexc.HTTPUnprocessableEntity(msg)

		user = User.get_user(username)
		if not user:
			raise hexc.HTTPUnprocessableEntity(_('User not found.'))

		if delete_purchase_history(user):
			logger.info("%s purchase history has been removed", user)

		return hexc.HTTPNoContent()

@view_config(name="GeneratePurchaseInvoice")
@view_config(name="generate_purchase_invoice")
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   context=StorePathAdapter,
			   request_method='POST')
class GeneratePurchaseInvoiceWitStripeView(_BasePostStoreView):

	def _get_purchase(self, key):
		try:
			integer_strings.from_external_string(key)
			purchase = get_purchase_by_code(key)
		except ValueError:
			purchase = get_purchase_attempt(key)
		return purchase

	def __call__(self):
		values = self.readInput()
		transaction = 	 values.get('code') \
					  or values.get('purchase')  \
					  or values.get('purchaseId') \
					  or values.get('transaction')
		if not transaction:
			msg = _("Must specified a valid transaction or purchase code.")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = self._get_purchase(transaction)
		if purchase is None:
			raise hexc.HTTPUnprocessableEntity(detail=_('Transaction not found.'))
		elif not purchase.has_succeeded():
			raise hexc.HTTPUnprocessableEntity(detail=_('Purchase was not successful.'))

		manager = component.getUtility(IPaymentProcessor, name=purchase.Processor)
		payment_charge = manager.get_payment_charge(purchase)

		notify(PurchaseAttemptSuccessful(purchase, payment_charge, request=self.request))
		return hexc.HTTPNoContent()

@view_config(name="CreateInvitationPurchase")
@view_config(name="create_invitation_purchase")
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   context=StorePathAdapter,
			   request_method='POST')
class CreateInviationPurchaseAttemptView(_BasePostStoreView):

	def price_order(self, order):
		pricer = component.getUtility(IPurchasablePricer)
		result = pricer.evaluate(order)
		return result

	def price_purchase(self, purchase):
		result = self.price_order(purchase.Order)
		return result

	def create_purchase_attempt(self, item, quantity=None, expirationTime=None,
								processor=PAYMENT_PROCESSORS[0]):
		state = PA_STATE_SUCCESS
		p_item = create_purchase_item(item, 1)
		p_order = create_purchase_order(p_item, quantity=quantity)
		purchase = create_purchase_attempt(p_order,
											state=state,
											processor=processor,
									 		expiration=expirationTime)
		purchase.Pricing = self.price_purchase(purchase)
		return purchase

	def __call__(self):
		values = self.readInput()
		purchasable_id = 	values.get('item') \
						 or values.get('ntiid') \
						 or values.get('purchasable') \
						 or values.get('purchasableId')
		if not purchasable_id:
			msg = _("Must specify a valid purchasable.")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = get_purchasable(purchasable_id)
		if not purchase:
			msg = _('Purchasable not found')
			raise hexc.HTTPUnprocessableEntity(msg)

		quantity = values.get('quantity') or 0
		if not is_valid_pve_int(quantity):
			msg = _('Must specify a valid quantity.')
			raise hexc.HTTPUnprocessableEntity(msg)

		expiration = values.get('expiration') or values.get('expiry') or \
					 values.get('expirationTime') or values.get('expirationDate')
		if expiration:
			expirationTime = parse_datetime(expiration, safe=True)
			if expirationTime is None:
				msg = _('Invalid expiration date/time.')
				raise hexc.HTTPUnprocessableEntity(msg)
		else:
			expirationTime = None

		user = self.remoteUser
		hist = IPurchaseHistory(user)
		purchase = self.create_purchase_attempt(purchasable_id, quantity=quantity,
												expirationTime=expirationTime)
		hist.add_purchase(purchase)

		logger.info("Invitation purchase %s created for user %s. " +
					"Redemption(s) %s. Expiration %s",
					get_invitation_code(purchase), user, quantity, expiration)
		return purchase
