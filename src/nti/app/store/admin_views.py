#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from . import MessageFactory as _

import isodate
from datetime import datetime
from cStringIO import StringIO

from pyramid.threadlocal import get_current_request

from zope import component
from zope.event import notify
from zope import lifecycleevent
from zope.annotation import IAnnotations

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.dataserver import users
from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IShardLayout
from nti.dataserver.users.interfaces import IUserProfile

from nti.externalization import integer_strings
from nti.externalization.interfaces import LocatedExternalDict

from nti.ntiids import ntiids

from nti.store.purchasable import get_purchasable
from nti.store.purchase_history import activate_items
from nti.store.purchase_history import PurchaseHistory
from nti.store.purchase_history import deactivate_items
from nti.store.purchase_history import get_purchase_attempt
from nti.store.purchase_history import remove_purchase_attempt
from nti.store.purchase_history import get_purchase_history_by_item

from nti.store.content_roles import add_users_content_roles
from nti.store.content_roles import get_users_content_roles
from nti.store.content_roles import remove_users_content_roles

from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IPurchaseHistory
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import PurchaseAttemptSuccessful

from nti.store.invitations import get_invitation_code
from nti.store.invitations import get_purchase_by_code

from nti.utils.maps import CaseInsensitiveDict

from ._utils import to_boolean
from ._utils import AbstractPostView

from .views import StorePathAdapter

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

@view_config(name="get_content_roles", **_view_admin_defaults)
class GetContentRolesView(AbstractAuthenticatedView):

	def __call__(self):
		request = self.request
		params = CaseInsensitiveDict(request.params)
		username = params.get('username') or request.authenticated_userid
		user = users.User.get_user(username)
		if not user:
			raise hexc.HTTPNotFound(detail=_('User not found'))

		roles = get_users_content_roles(user)
		result = LocatedExternalDict()
		result['Username'] = username
		result['Items'] = roles
		return result

@view_config(name="get_users_purchase_history", **_view_admin_defaults)
class GetUsersPurchaseHistoryView(AbstractAuthenticatedView):

	def _to_csv(self, request, result):
		response = request.response
		response.content_type = b'text/csv; charset=UTF-8'
		response.content_disposition = b'attachment; filename="purchases.csv"'

		header = ("username", 'name', 'email', 'transaction', 'date', 'amount', 'status')
		stream = StringIO()
		stream.write(",".join(header))
		stream.write("\n")
		for entry in result['Items']:
			username = entry['username'].encode('utf-8', 'replace')
			name = entry['name'].encode('utf-8', 'replace')
			email = entry['email']
			transactions = entry['transactions']
			for trx in transactions:
				line = "%s,%s,%s,%s,%s,%s,%s," % (username, name, email,
												  trx['transaction'],
												  trx['date'],
												  trx['amount'],
												  trx['status'])
				stream.write(line)
				stream.write("\n")
		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

	def __call__(self):
		request = self.request
		params = CaseInsensitiveDict(request.params)
		purchasable_id = params.get('purchasableID') or params.get('purchasable_id')
		if not purchasable_id:
			msg = _("Must specify a valid purchasable id")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchasable_obj = get_purchasable(purchasable_id)
		if not purchasable_obj:
			raise hexc.HTTPNotFound(detail=_('Purchasable not found'))

		usernames = params.get('usernames', None)
		if usernames:
			usernames = usernames.split(",")
		else:
			dataserver = component.getUtility(IDataserver)
			_users = IShardLayout(dataserver).users_folder
			usernames = _users.keys()

		as_csv = to_boolean(params.get('csv'))
		all_succeeded = to_boolean(params.get('succeeded'))
		all_failed = to_boolean(params.get('failed'))
		inactive = to_boolean(params.get('inactive')) or False

		annotation_key = "%s.%s" % (PurchaseHistory.__module__, PurchaseHistory.__name__)

		items = []
		result = LocatedExternalDict({'Items':items})
		for username in usernames:
			user = users.User.get_user(username)
			if not user or not IUser.providedBy(user):
				continue
			annotations = IAnnotations(user, {})
			if annotation_key not in annotations:
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

		result = result if not as_csv else self._to_csv(request, result)
		return result

# post views

_BasePostStoreView = AbstractPostView # alias

@view_config(name="permission_purchasable", **_admin_view_defaults)
class PermissionPurchasableView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		username = values.get('username') or self.request.authenticated_userid
		user = users.User.get_user(username)
		if not user:
			raise hexc.HTTPNotFound(detail=_('User not found'))

		purchasable_id = values.get('purchasableID') or values.get('purchasable_id')
		purchasable_obj = get_purchasable(purchasable_id) if purchasable_id else None
		if not purchasable_obj:
			raise hexc.HTTPNotFound(detail=_('Purchasable not found'))

		add_users_content_roles(user, purchasable_obj.Items)
		logger.info("Activating %s for user %s" % (purchasable_id, user))
		activate_items(user, purchasable_id)

		return hexc.HTTPNoContent()

@view_config(name="unpermission_purchasable", **_admin_view_defaults)
class UnPermissionPurchasableView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		username = values.get('username') or self.request.authenticated_userid
		user = users.User.get_user(username)
		if not user:
			raise hexc.HTTPNotFound(detail=_('User not found'))

		purchasable_id = values.get('purchasableID', u'')
		purchasable_obj = get_purchasable(purchasable_id)
		if not purchasable_obj:
			raise hexc.HTTPNotFound(detail=_('Purchasable not found'))

		remove_users_content_roles(user, purchasable_obj.Items)
		deactivate_items(user, purchasable_id)
		logger.info("%s deactivated for user %s" % (purchasable_id, user))

		return hexc.HTTPNoContent()

@view_config(name="delete_purchase_attempt", **_admin_view_defaults)
class DeletePurchaseAttemptView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		purchase_id = values.get('purchaseid') or values.get('purchase_id')
		if not purchase_id:
			msg = _("Must specify a valid purchase attempt id")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = get_purchase_attempt(purchase_id)
		if not purchase:
			raise hexc.HTTPNotFound(detail=_('Purchase attempt not found'))
		
		remove_purchase_attempt(purchase, purchase.creator)
		logger.info("Purchase attempt '%s' has been deleted")
		return hexc.HTTPNoContent()

@view_config(name="delete_purchase_history", **_admin_view_defaults)
class DeletePurchaseHistoryView(_BasePostStoreView):

	def __call__(self):
		values = self.readInput()
		username = values.get('username') or self.request.authenticated_userid
		user = users.User.get_user(username)
		if not user:
			raise hexc.HTTPNotFound(detail=_('User not found'))

		annotations = IAnnotations(user)
		annotation_key = "%s.%s" % (PurchaseHistory.__module__, PurchaseHistory.__name__)

		if annotation_key in annotations:
			su = IPurchaseHistory(user)
			for p in su.values():
				lifecycleevent.removed(p)
			del annotations[annotation_key]
			logger.info("Purchase history has been removed for user %s", user)

		return hexc.HTTPNoContent()

@view_config(name="generate_purchase_invoice", **_admin_view_defaults)
class GeneratePurchaseInvoiceWitStripeView(_BasePostStoreView):

	def _get_purchase(self, key):
		try:
			integer_strings.from_external_string(key)
			purchase = get_purchase_by_code(key)
		except ValueError:
			if ntiids.is_valid_ntiid_string(key):
				purchase = ntiids.find_object_with_ntiid(key)
			else:
				purchase = None
		return purchase

	def __call__(self):
		values = self.readInput()
		transaction = values.get('transaction') or \
					  values.get('purchaseId') or \
					  values.get('code')
		if not transaction:
			msg = _("Must specified a valid transaction or purchase code")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = self._get_purchase(transaction)
		if purchase is None or not IPurchaseAttempt.providedBy(purchase):
			raise hexc.HTTPNotFound(detail=_('Transaction not found'))
		elif not purchase.has_succeeded():
			raise hexc.HTTPUnprocessableEntity(detail=_('Purchase was not successful'))

		manager = component.getUtility(IPaymentProcessor, name=self.processor)
		payment_charge = manager.get_payment_charge(purchase)

		notify(PurchaseAttemptSuccessful(purchase, payment_charge,
										 request=get_current_request()))
		return hexc.HTTPNoContent()
	
del _view_defaults
del _post_view_defaults
del _admin_view_defaults
del _view_admin_defaults
