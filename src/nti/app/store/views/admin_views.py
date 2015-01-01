#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

import csv
import isodate
from io import BytesIO
from datetime import datetime

from zope import component
from zope.event import notify

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.dataserver.users import User
from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IShardLayout
from nti.dataserver.users.interfaces import IUserProfile

from nti.externalization import integer_strings
from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store.store import get_gift_code
from nti.store.store import get_gift_registry
from nti.store.store import get_invitation_code
from nti.store.store import get_purchase_by_code
from nti.store.store import get_purchase_attempt
from nti.store.store import get_purchase_history
from nti.store.store import delete_purchase_history
from nti.store.store import remove_purchase_attempt
from nti.store.store import get_gift_purchase_history

from nti.store.purchase_order import create_purchase_item
from nti.store.purchase_order import create_purchase_order
from nti.store.purchase_attempt import create_purchase_attempt

from nti.store.purchasable import get_purchasable
from nti.store.purchase_history import get_purchase_history_by_item

from nti.store.interfaces import PA_STATE_SUCCESS
from nti.store.interfaces import PAYMENT_PROCESSORS

from nti.store.interfaces import IPurchaseHistory
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import PurchaseAttemptSuccessful

from nti.utils.maps import CaseInsensitiveDict

from ..utils import to_boolean
from ..utils import parse_datetime
from ..utils import AbstractPostView
from ..utils import is_valid_pve_int

from . import StorePathAdapter

ITEMS = StandardExternalFields.ITEMS

_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=StorePathAdapter,
					  request_method='GET')
_view_admin_defaults = _view_defaults.copy()
_view_admin_defaults['permission'] = nauth.ACT_MODERATE

_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

_admin_view_defaults = _post_view_defaults.copy()
_admin_view_defaults['permission'] = nauth.ACT_MODERATE

def _tx_string(s):
	if s is not None and isinstance(s, unicode):
		s = s.encode('utf-8')
	return s

@view_config(name="get_users_purchase_history", **_view_admin_defaults)
class GetUsersPurchaseHistoryView(AbstractAuthenticatedView):

	def _to_csv(self, request, result):
		stream = BytesIO()
		writer = csv.writer(stream)
		response = request.response
		response.content_encoding = str('identity' )
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str( 'attachment; filename="purchases.csv"' )
		
		header = ["username", 'name', 'email', 'transaction', 'date', 'amount', 'status']
		writer.writerow(header)
		
		for entry in result[ITEMS]:
			email = entry['email']
			transactions = entry['transactions']
			name = entry['name'].encode('utf-8', 'replace')
			username = entry['username'].encode('utf-8', 'replace')
			for trx in transactions:
				row_data = [ username, name, email,
							 trx['transaction'],
							 trx['date'],
							 trx['amount'],
							 trx['status'] ]
				writer.writerow([ _tx_string(x) for x in row_data])

		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

	def __call__(self):
		request = self.request
		params = CaseInsensitiveDict(request.params)
		purchasable_id = params.get('purchasableID') or params.get('purchasable')
		if not purchasable_id:
			msg = _("Must specify a valid purchasable id")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchasable_obj = get_purchasable(purchasable_id)
		if not purchasable_obj:
			raise hexc.HTTPUnprocessableEntity(detail=_('Purchasable not found'))

		usernames = params.get('usernames') or params.get('username')
		if usernames:
			usernames = usernames.split(",")
		else:
			dataserver = component.getUtility(IDataserver)
			users_folder = IShardLayout(dataserver).users_folder
			usernames = users_folder.keys()

		as_csv = to_boolean(params.get('csv'))
		
		all_failed = to_boolean(params.get('failed'))
		all_succeeded = to_boolean(params.get('succeeded'))
		
		inactive = to_boolean(params.get('inactive')) or False

		items = []
		result = LocatedExternalDict({ITEMS:items})
		for username in usernames:
			user = User.get_user(username)
			if not user or not IUser.providedBy(user):
				continue
			history = get_purchase_history(user, safe=False)
			if history is None:
				continue

			purchases = get_purchase_history_by_item(user, purchasable_id)
			if all_succeeded:
				array = [p for p in purchases if p.has_succeeded()]
			elif all_failed:
				array = [p for p in purchases if p.has_failed()]
			else:
				array = purchases

			if array or inactive:
				profile = IUserProfile(user)
				email = getattr(profile, 'email', None) or u''
				name = getattr(profile, 'realname', None) or user.username

				transactions = []
				entry = {'username':user.username,
						 'name':name,
						 'email':email,
						 'transactions':transactions}

				for p in purchases:
					code = get_invitation_code(p)
					date = isodate.date_isoformat(datetime.fromtimestamp(p.StartTime))
					amount = getattr(p.Pricing, 'TotalPurchasePrice', None) or u''
					transactions.append({'transaction':code, 'date':date,
										 'amount':amount, 'status':p.State})
				items.append(entry)

		result['Total'] = len(items)
		result = result if not as_csv else self._to_csv(request, result)
		return result

@view_config(name="get_users_gift_history", **_view_admin_defaults)
class GetUsersGiftHistoryView(AbstractAuthenticatedView):

	def __call__(self):
		request = self.request
		params = CaseInsensitiveDict(request.params)
		usernames = params.get('usernames') or params.get('username')
		if usernames:
			usernames = set(usernames.split(","))
	
		all_failed = to_boolean(params.get('failed'))
		all_succeeded = to_boolean(params.get('succeeded'))

		end_time = parse_datetime(params.get('endTime', None))
		start_time = parse_datetime(params.get('startTime', None))
			
		stream = BytesIO()
		writer = csv.writer(stream)
		response = request.response
		response.content_encoding = str('identity' )
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str( 'attachment; filename="gifts.csv"' )
		
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

_BasePostStoreView = AbstractPostView # alias

@view_config(name="delete_purchase_attempt", **_admin_view_defaults)
class DeletePurchaseAttemptView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		purchase_id = 	values.get('purchaseId') or \
						values.get('purchase')
		if not purchase_id:
			msg = _("Must specify a valid purchase attempt id")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = get_purchase_attempt(purchase_id)
		if not purchase:
			msg = _('Purchase attempt not found')
			raise hexc.HTTPNotFound(msg)
		
		if remove_purchase_attempt(purchase, purchase.creator):
			logger.info("Purchase attempt '%s' has been deleted")
		return hexc.HTTPNoContent()

@view_config(name="delete_purchase_history", **_admin_view_defaults)
class DeletePurchaseHistoryView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		username = values.get('username')
		if not username:
			msg = _("Must specify a valid username")
			raise hexc.HTTPUnprocessableEntity(msg)
		
		user = User.get_user(username)
		if not user:
			raise hexc.HTTPUnprocessableEntity(_('User not found'))

		if delete_purchase_history(user):
			logger.info("%s purchase history has been removed", user)

		return hexc.HTTPNoContent()

@view_config(name="generate_purchase_invoice", **_admin_view_defaults)
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
		transaction = values.get('transaction') or \
					  values.get('purchaseId') or \
					  values.get('purchase') or \
					  values.get('code')
		if not transaction:
			msg = _("Must specified a valid transaction or purchase code")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = self._get_purchase(transaction)
		if purchase is None:
			raise hexc.HTTPUnprocessableEntity(detail=_('Transaction not found'))
		elif not purchase.has_succeeded():
			raise hexc.HTTPUnprocessableEntity(detail=_('Purchase was not successful'))

		manager = component.getUtility(IPaymentProcessor, name=purchase.Processor)
		payment_charge = manager.get_payment_charge(purchase)

		notify(PurchaseAttemptSuccessful(purchase, payment_charge, request=self.request))
		return hexc.HTTPNoContent()
	
@view_config(name="create_invitation_purchase", **_admin_view_defaults)
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
		purchase = create_purchase_attempt(	p_order, 
											state=state,
											processor=processor,
									 		expiration=expirationTime)
		purchase.Pricing = self.price_purchase(purchase)
		return purchase

	def __call__(self):
		values = self.readInput()
		purchasable_id = values.get('purchasable') or values.get('item') or\
						 values.get('purchasableId')
		if not purchasable_id:
			msg = _("Must specify a valid purchasable")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = get_purchasable(purchasable_id)
		if not purchase:
			msg = _('Purchasable not found')
			raise hexc.HTTPUnprocessableEntity(msg)
		
		quantity = values.get('quantity') or 0
		if not is_valid_pve_int(quantity):
			msg = _('Must specify a valid quantity')
			raise hexc.HTTPUnprocessableEntity(msg)
		
		expiration = values.get('expiration') or values.get('expiry') or \
					 values.get('expirationTime') or values.get('expirationDate')
		if expiration:
			expirationTime = parse_datetime(expiration, safe=True)
			if expirationTime is None:
				msg = _('Invalid expiration date/time')
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
		
del _view_defaults
del _post_view_defaults
del _admin_view_defaults
del _view_admin_defaults