#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

import six
import time
import gevent
import isodate
import numbers
from urllib import unquote
from functools import partial

from zope import component
from zope import interface
from zope.event import notify
from zope.container.contained import Contained
from zope.traversing.interfaces import IPathAdapter

from pyramid.view import view_config
from pyramid import httpexceptions as hexc
from pyramid.authorization import ACLAuthorizationPolicy

from nti.app.authentication import get_remote_user
from nti.app.renderers.interfaces import IUncacheableInResponse

from nti.app.base.abstract_views import AbstractView
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.appserver.dataserver_pyramid_views import _GenericGetView as GenericGetView

from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverTransactionRunner

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store import InvalidPurchasable
from nti.store.priceable import create_priceable

from nti.site.site import get_site_for_site_names

from nti.store import RedemptionException

from nti.store.purchasable import get_all_purchasables

from nti.store.store import get_purchase_by_code

from nti.store.invitations import InvitationAlreadyAccepted
from nti.store.invitations import InvitationCapacityExceeded
from nti.store.invitations import create_store_purchase_invitation

from nti.store.store import get_purchase_attempt
from nti.store.store import get_gift_pending_purchases

from nti.store.purchase_history import get_purchase_history
from nti.store.purchase_history import get_pending_purchases
from nti.store.purchase_history import get_purchase_history_by_item

from nti.store.interfaces import IPurchasable
from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IRedemptionError
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import IGiftPurchaseAttempt
from nti.store.interfaces import GiftPurchaseAttemptRedeemed

from nti.utils.maps import CaseInsensitiveDict

from ..utils import AbstractPostView
from ..utils import is_valid_pve_int
from ..utils import is_valid_timestamp

from .. import STORE
from .. import get_possible_site_names

ITEMS = u'Items'
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED

@interface.implementer(IPathAdapter)
class StorePathAdapter(Contained):

	__name__ = STORE

	def __init__(self, context, request):
		self.context = context
		self.request = request
		self.__parent__ = context

_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=StorePathAdapter,
					  request_method='GET')
_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

_noauth_view_defaults = _view_defaults.copy()
_noauth_view_defaults.pop('permission', None)

_noauth_post_defaults = _post_view_defaults.copy()
_noauth_post_defaults.pop('permission', None)

# get views

def _last_modified(purchases=()):
	result = 0
	if purchases:
		result = max(map(lambda x: getattr(x, "lastModified", 0), purchases))
	return result

@view_config(name="get_pending_purchases", **_view_defaults)
class GetPendingPurchasesView(AbstractAuthenticatedView):

	def __call__(self):
		username = self.remoteUser.username
		purchases = get_pending_purchases(username)
		result = LocatedExternalDict()
		result[ITEMS] = purchases
		result[LAST_MODIFIED] = _last_modified(purchases)
		return result

@view_config(name="get_gift_pending_purchases", **_noauth_view_defaults)
class GetGiftPendingPurchasesView(AbstractAuthenticatedView):

	def __call__(self):
		values = CaseInsensitiveDict(self.request.params)
		if self.remoteUser is None:
			username = values.get('username') or values.get('user')
		else:
			username = self.remoteUser.username
		if not username:
			raise hexc.HTTPUnprocessableEntity(_('Must provide a user name'))
		purchases = get_gift_pending_purchases(username)
		result = LocatedExternalDict()
		result[ITEMS] = purchases
		result[LAST_MODIFIED] = _last_modified(purchases)
		return result

@view_config(name="get_purchase_history", **_view_defaults)
class GetPurchaseHistoryView(AbstractAuthenticatedView):

	def _parse_datetime(self, t):
		result = t
		if is_valid_timestamp(t):
			result = float(t)
		elif isinstance(t, six.string_types):
			result = time.mktime(isodate.parse_datetime(t).timetuple())
		return result if isinstance(t, numbers.Number) else None

	def __call__(self):
		request = self.request
		username = self.remoteUser.username
		values = CaseInsensitiveDict(request.params)
		purchasable_id = values.get('purchasableID') or \
						 values.get('purchasable_id') or \
						 values.get('purchasable')
		if not purchasable_id:
			end_time = self._parse_datetime(values.get('endTime', None))
			start_time = self._parse_datetime(values.get('startTime', None))
			purchases = get_purchase_history(username, start_time, end_time)
		else:
			purchases = get_purchase_history_by_item(username, purchasable_id)
		result = LocatedExternalDict()
		result[ITEMS] = purchases
		result[LAST_MODIFIED] = _last_modified(purchases)
		return result

def _sync_purchase(purchase, request):
	purchase_id = purchase.id
	creator = purchase.creator
	username = getattr(creator, 'username', creator)
	site_names = get_possible_site_names(request)
	
	def sync_purchase():
		manager = component.getUtility(IPaymentProcessor, name=purchase.Processor)
		manager.sync_purchase(purchase_id=purchase_id,
							  username=username,
							  request=request)

	def process_sync():
		transaction_runner = component.getUtility(IDataserverTransactionRunner)
		transaction_runner = partial(transaction_runner, site_names=site_names)
		transaction_runner(sync_purchase)

	gevent.spawn(process_sync)

def _should_sync(purchase, now=None):
	now = now or time.time()
	start_time = purchase.StartTime
	## CS: 100 is the [magic] number of seconds elapsed since the purchase
	## attempt was started. After this time, we try to get the purchase
	## status by asking its payment processor
	result = now - start_time >= 100 and not purchase.is_synced()
	return result

class BaseGetPurchaseAttemptView(object):

	def _do_get(self, purchase_id, username=None):
		if not purchase_id:
			msg = _("Must specify a valid purchase attempt id")
			raise hexc.HTTPUnprocessableEntity(msg)
		
		if not username:
			msg = _("Must specify a valid user/creator name")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = get_purchase_attempt(purchase_id, username)
		if purchase is None:
			raise hexc.HTTPNotFound(detail=_('Purchase attempt not found'))
		elif purchase.is_pending() and _should_sync(purchase):
			_sync_purchase(purchase, self.request)

		result = LocatedExternalDict()
		result[ITEMS] = [purchase]
		result[LAST_MODIFIED] = purchase.lastModified
		interface.alsoProvides(result, IUncacheableInResponse)
		return result
	
@view_config(name="get_purchase_attempt", **_view_defaults)
class GetPurchaseAttemptView(AbstractAuthenticatedView, BaseGetPurchaseAttemptView):

	def __call__(self):
		username = self.remoteUser.username
		values = CaseInsensitiveDict(self.request.params)
		purchase_id = 	values.get('purchaseID') or \
						values.get('purchase_id') or \
						values.get('purchase')
		result = self._do_get(purchase_id, username)
		return result

@view_config(name="get_gift_purchase_attempt", **_noauth_view_defaults)
class GetGiftPurchaseAttemptView(AbstractView, BaseGetPurchaseAttemptView):

	def __call__(self):
		values = CaseInsensitiveDict(self.request.params)
		purchase_id = 	values.get('purchaseID') or \
						values.get('purchase_id') or \
						values.get('purchase')
		username = 	values.get('username') or \
					values.get('creator') or \
					values.get('sender') or \
					values.get('from')
		result = self._do_get(purchase_id, username)
		return result

def check_purchasable_access(purchasable, remoteUser=None):
	is_authenticated = (remoteUser is not None)
	return is_authenticated or purchasable.Giftable

@view_config(name="get_purchasables", **_noauth_view_defaults)
class GetPurchasablesView(AbstractAuthenticatedView):

	def _is_permitted(self, p):
		if hasattr(p, 'HACK_make_acl'):
			acl = p.HACK_make_acl()
			class Dummy(object):
				__acl__ = None
			dummy = Dummy()
			dummy.__acl__ = acl
			policy = ACLAuthorizationPolicy()
			principals = self.request.effective_principals
			result = policy.permits(dummy, principals, nauth.ACT_READ)
		else:
			result = True
		return result

	def _check_access(self, purchasable):
		is_authenticated = (self.remoteUser is not None)
		result = purchasable.isPublic and \
				 ( (is_authenticated and self._is_permitted(purchasable)) or \
				 	check_purchasable_access(purchasable, self.remoteUser) )
		return result

	def __call__(self):
		values = CaseInsensitiveDict(self.request.params)
		ntiids = values.get("purchasable") or values.get('purchasables')
		if ntiids:
			ntiids = ntiids.split()
			ntiids = {unquote(x).lower() for x in ntiids}
			
		purchasables = []
		for p in get_all_purchasables():
			if 	self._check_access(p) and \
				(not ntiids or p.NTIID.lower() in ntiids):
				purchasables.append(p)
		result = LocatedExternalDict()
		result[ITEMS] = purchasables
		result[LAST_MODIFIED] = 0
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=IPurchasable,
			 request_method='GET')
class PurchasableGetView(GenericGetView):
	
	def __call__(self):
		result = GenericGetView.__call__(self)
		if 	result is not None and \
			not check_purchasable_access(result, get_remote_user(self.request)):
			raise hexc.HTTPForbidden()
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=IPurchaseAttempt,
			 request_method='GET')
class PurchaseAttemptGetView(GenericGetView):

	def __call__(self):
		purchase = super(PurchaseAttemptGetView, self).__call__()
		if purchase.is_pending() and _should_sync(purchase):
			_sync_purchase(purchase, self.request)
		return purchase

# post views

@view_config(name="price_purchasable", **_noauth_post_defaults)
class PricePurchasableView(AbstractPostView):

	def price(self, purchasable_id, quantity):
		pricer = component.getUtility(IPurchasablePricer)
		source = create_priceable(purchasable_id, quantity)
		result = pricer.price(source)
		return result

	def price_purchasable(self, values=None):
		values = values or self.readInput()
		purchasable_id = values.get('purchasableID') or \
						 values.get('purchasable_id') or \
						 values.get('purchasable') or u''

		# check quantity
		quantity = values.get('quantity', 1)
		if not is_valid_pve_int(quantity):
			raise hexc.HTTPBadRequest(_('Invalid quantity'))
		quantity = int(quantity)

		try:
			result = self.price(purchasable_id, quantity)
			return result
		except InvalidPurchasable:
			raise hexc.HTTPUnprocessableEntity(_('Purchasable not found'))

	def __call__(self):
		result = self.price_purchasable()
		return result

@view_config(name="redeem_purchase_code", **_post_view_defaults)
class RedeemPurchaseCodeView(AbstractPostView):

	def __call__(self):
		values = self.readInput()
		purchasable_id = values.get('purchasableID') or \
						 values.get('purchasable_id') or \
						 values.get('purchasable')
		if not purchasable_id:
			msg = _("Must specify a valid purchasable id")
			raise hexc.HTTPUnprocessableEntity(msg)

		invitation_code = values.get('invitationCode') or \
						  values.get('invitation_code') or \
						  values.get('invitation') or \
 						  values.get('code')
		if not invitation_code:
			msg = _("Must specify a valid invitation code")
			raise hexc.HTTPUnprocessableEntity(msg)

		try:
			purchase = get_purchase_by_code(invitation_code)
		except ValueError:
			# improper key
			purchase = None

		if purchase is None or not IPurchaseAttempt.providedBy(purchase):
			raise hexc.HTTPNotFound(detail=_('Purchase attempt not found'))

		if purchase.Quantity is None:
			raise hexc.HTTPUnprocessableEntity(detail=_('Not redeemable purchase'))

		if purchasable_id not in purchase.Items:
			msg = _("The invitation code is not for this purchasable")
			raise hexc.HTTPUnprocessableEntity(msg)

		username = self.remoteUser.username
		try:
			invite = create_store_purchase_invitation(purchase, invitation_code)
			invite.accept(username)
		except InvitationAlreadyAccepted:
			msg = _("The invitation code has already been accepted")
			raise hexc.HTTPUnprocessableEntity(msg)
		except InvitationCapacityExceeded:
			msg = _("There are no remaining invitations for this code")
			raise hexc.HTTPUnprocessableEntity(msg)

		return hexc.HTTPNoContent()

@view_config(name="redeem_gift", **_post_view_defaults)
class RedeemGiftView(AbstractPostView):

	def __call__(self):
		values = self.readInput()
		gift_code = values.get('code') or \
					values.get('gift') or \
					values.get('giftCode')
		if not gift_code:
			msg = _("Must specify a valid gift code")
			raise hexc.HTTPUnprocessableEntity(msg)

		try:
			purchase = get_purchase_by_code(gift_code)
		except ValueError:
			# improper key
			purchase = None

		if purchase is None or not IGiftPurchaseAttempt.providedBy(purchase):
			self.request.response.status_int = 404
			result = IRedemptionError(_('Purchase gift not found'))
			return result

		user = self.remoteUser
		try:
			if purchase.is_redeemed():
				result = IRedemptionError(_("Gift purchase already redeemded"))
				self.request.response.status_int = 422
			notify(GiftPurchaseAttemptRedeemed(purchase, user, self.request))
		except RedemptionException as e:
			result = IRedemptionError(e)
			self.request.response.status_int = 422
		else:
			result = hexc.HTTPNoContent()
		return result

# object get views

del _view_defaults
del _post_view_defaults
del _noauth_post_defaults
del _noauth_view_defaults
