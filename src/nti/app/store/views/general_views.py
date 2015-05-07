#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

import time
import gevent
from urllib import unquote
from functools import partial

from zope import component
from zope import interface

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.authentication import get_remote_user

from nti.app.base.abstract_views import AbstractView
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.renderers.interfaces import IUncacheableInResponse

from nti.appserver.dataserver_pyramid_views import _GenericGetView as GenericGetView

from nti.common.maps import CaseInsensitiveDict

from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverTransactionRunner

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.store import InvalidPurchasable
from nti.store.priceable import create_priceable

from nti.store import PricingException

from nti.store.purchasable import get_all_purchasables

from nti.store.store import get_purchase_by_code

from nti.store.store import get_purchase_attempt
from nti.store.store import get_gift_pending_purchases

from nti.store.purchase_history import get_purchase_history
from nti.store.purchase_history import get_pending_purchases
from nti.store.purchase_history import get_purchase_history_by_item

from nti.store.interfaces import IPurchasable
from nti.store.interfaces import IPricingError
from nti.store.interfaces import IPurchaseOrder
from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer

from ..utils import AbstractPostView

from ..utils import parse_datetime
from ..utils import is_valid_pve_int

from .. import get_possible_site_names

from . import StorePathAdapter

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED

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

	def __call__(self):
		request = self.request
		username = self.remoteUser.username
		values = CaseInsensitiveDict(request.params)
		purchasable_id = values.get('purchasableId') or \
						 values.get('purchasable')
		if not purchasable_id:
			end_time = parse_datetime(values.get('endTime', None))
			start_time = parse_datetime(values.get('startTime', None))
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

		try:
			purchase = get_purchase_by_code(purchase_id)
			purchase_id = purchase.id if purchase is not None else purchase_id
		except ValueError:
			pass
	
		purchase = get_purchase_attempt(purchase_id, username)
		if purchase is None:
			raise hexc.HTTPNotFound(detail=_('Purchase attempt not found'))
		elif purchase.is_pending() and _should_sync(purchase):
			_sync_purchase(purchase, self.request)

		## CS: we return the purchase attempt inside a ITEMS collection
		## due to legacy code
		result = LocatedExternalDict()
		result[ITEMS] = [purchase]
		result[LAST_MODIFIED] = purchase.lastModified
		interface.alsoProvides(result, IUncacheableInResponse)
		return result

@view_config(name="get_purchase_attempt", **_view_defaults)
class GetPurchaseAttemptView(AbstractAuthenticatedView, BaseGetPurchaseAttemptView):

	def __call__(self):
		request = self.request
		username = self.remoteUser.username
		purchase_id = request.subpath[0] if request.subpath else None
		if not purchase_id:
			values = CaseInsensitiveDict(self.request.params)
			purchase_id = 	values.get('purchaseId') or \
							values.get('purchase')
		result = self._do_get(purchase_id, username)
		return result

@view_config(name="get_gift_purchase_attempt", **_noauth_view_defaults)
class GetGiftPurchaseAttemptView(AbstractView, BaseGetPurchaseAttemptView):

	def __call__(self):
		values = CaseInsensitiveDict(self.request.params)
		purchase_id = values.get('purchaseId') or \
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

	def _check_access(self, purchasable):
		result = purchasable.isPublic and \
				 check_purchasable_access(purchasable, self.remoteUser)
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

def check_purchase_attempt_access(purchase, username):
	creator = purchase.creator
	creator = getattr(creator, 'username', creator)
	result = creator.lower() == username.lower()
	return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=IPurchaseAttempt,
			 request_method='GET')
class PurchaseAttemptGetView(GenericGetView):

	def __call__(self):
		username = self.request.authenticated_userid
		purchase = super(PurchaseAttemptGetView, self).__call__()
		if not check_purchase_attempt_access(purchase, username):
			raise hexc.HTTPForbidden()
		if purchase.is_pending() and _should_sync(purchase):
			_sync_purchase(purchase, self.request)
		return purchase

# post views

def perform_pricing(purchasable, quantity):
	pricer = component.getUtility(IPurchasablePricer)
	priceable = create_priceable(ntiid=purchasable, quantity=quantity)
	result = pricer.price(priceable)
	return result

def price_order(order):
	pricer = component.getUtility(IPurchasablePricer)
	result = pricer.evaluate(order)
	return result

def _call_pricing_func(func):
	try:
		result = func()
	except InvalidPurchasable:
		result = IPricingError(_("Invalid purchasable"))
	except PricingException as e:
		result = IPricingError(e)
	except Exception:
		raise
	return result

@view_config(name="price_purchasable", **_noauth_post_defaults)
class PricePurchasableView(AbstractPostView):

	def price_purchasable(self, values=None):
		values = values or self.readInput()
		purchasable = values.get('purchasable ') or \
					  values.get('purchasableId') or \
					  values.get('purchasable_id') or u''

		# check quantity
		quantity = values.get('quantity', 1)
		if not is_valid_pve_int(quantity):
			raise hexc.HTTPUnprocessableEntity(_('Invalid quantity'))
		quantity = int(quantity)

		pricing_func = partial(perform_pricing, 
					   		   quantity=quantity,
					   		   purchasable=purchasable)
		result = _call_pricing_func(pricing_func)
		status = 422 if IPricingError.providedBy(result) else 200
		self.request.response.status_int = status
		return result

	def __call__(self):
		result = self.price_purchasable()
		return result

@view_config(name="price_order", **_noauth_post_defaults)
class PriceOrderView(AbstractAuthenticatedView,
					 ModeledContentUploadRequestUtilsMixin):
	
	content_predicate = IPurchaseOrder.providedBy

	def readCreateUpdateContentObject(self, *args, **kwargs):
		externalValue = self.readInput()
		result = find_factory_for(externalValue)()
		update_from_external_object(result, externalValue)
		return result
		
	def _do_call(self):
		order = self.readCreateUpdateContentObject()
		assert IPurchaseOrder.providedBy(order)

		result = _call_pricing_func(partial(price_order, order))
		status = 422 if IPricingError.providedBy(result) else 200
		self.request.response.status_int = status
		return result

# object get views

del _view_defaults
del _post_view_defaults
del _noauth_post_defaults
del _noauth_view_defaults