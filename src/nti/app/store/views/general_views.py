#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import time
from functools import partial
from six.moves.urllib_parse import unquote

import gevent

from requests.structures import CaseInsensitiveDict

from zope import component
from zope import interface

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.authentication import get_remote_user

from nti.app.base.abstract_views import AbstractView
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.renderers.interfaces import IUncacheableInResponse

from nti.app.store import MessageFactory as _

from nti.app.store.utils import parse_datetime
from nti.app.store.utils import is_valid_pve_int
from nti.app.store.utils import AbstractPostView

from nti.app.store.views import get_current_site
from nti.app.store.views import StorePathAdapter

from nti.app.store.views.view_mixin import price_order
from nti.app.store.views.view_mixin import PriceOrderViewMixin

from nti.appserver.dataserver_pyramid_views import GenericGetView

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IDataserverTransactionRunner

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store import InvalidPurchasable

from nti.store import PricingException

from nti.store.interfaces import IPurchasable
from nti.store.interfaces import IPricingError
from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer

from nti.store.priceable import create_priceable

from nti.store.purchasable import get_all_purchasables

from nti.store.purchase_history import get_purchase_history
from nti.store.purchase_history import get_pending_purchases
from nti.store.purchase_history import get_purchase_history_by_item

from nti.store.store import get_purchase_by_code
from nti.store.store import get_purchase_attempt
from nti.store.store import get_gift_pending_purchases

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED

logger = __import__('logging').getLogger(__name__)


# get views


def _last_modified(purchases=()):
    result = 0
    if purchases:
        result = max(getattr(x, "lastModified", 0) for x in purchases)
    return result


@view_config(name="GetPendingPurchases")
@view_config(name="get_pending_purchases")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='GET')
class GetPendingPurchasesView(AbstractAuthenticatedView):

    def __call__(self):
        username = self.remoteUser.username
        result = LocatedExternalDict()
        purchases = result[ITEMS] = get_pending_purchases(username)
        result[LAST_MODIFIED] = _last_modified(purchases)
        result[TOTAL] = result[ITEM_COUNT] = len(purchases)
        return result


@view_config(name="GetGiftPendingPurchases")
@view_config(name="get_gift_pending_purchases")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='GET')
class GetGiftPendingPurchasesView(AbstractAuthenticatedView):

    def __call__(self):
        values = CaseInsensitiveDict(self.request.params)
        if self.remoteUser is None:
            username = values.get('username') or values.get('user')
        else:
            username = self.remoteUser.username
        if not username:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Must provide a user name."),
                            'field': 'username'
                        },
                        None)
        purchases = get_gift_pending_purchases(username)
        result = LocatedExternalDict()
        result[ITEMS] = purchases
        result[LAST_MODIFIED] = _last_modified(purchases)
        result[TOTAL] = result[ITEM_COUNT] = len(purchases)
        return result


@view_config(name="GetPurchaseHistory")
@view_config(name="get_purchase_history")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='GET')
class GetPurchaseHistoryView(AbstractAuthenticatedView):

    def __call__(self):
        request = self.request
        username = self.remoteUser.username
        values = CaseInsensitiveDict(request.params)
        purchasable_id = values.get('ntiid') \
                      or values.get('purchasable') \
                      or values.get('purchasableId')
        if not purchasable_id:
            end_time = parse_datetime(values.get('endTime', None))
            start_time = parse_datetime(values.get('startTime', None))
            purchases = get_purchase_history(username, start_time, end_time)
        else:
            purchases = get_purchase_history_by_item(username, purchasable_id)
        result = LocatedExternalDict()
        result[ITEMS] = purchases
        result[LAST_MODIFIED] = _last_modified(purchases)
        result[TOTAL] = result[ITEM_COUNT] = len(purchases)
        return result


def _sync_purchase(purchase, request):
    purchase_id = purchase.id
    creator = purchase.creator
    processor = purchase.Processor
    site_name = get_current_site()
    username = getattr(creator, 'username', creator)

    def sync_purchase():
        manager = component.getUtility(IPaymentProcessor, name=processor)
        manager.sync_purchase(purchase_id=purchase_id,
                              username=username,
                              request=request)

    def process_sync():
        runner = component.getUtility(IDataserverTransactionRunner)
        runner(sync_purchase,
               site_names = (site_name,) if site_name else ())

    gevent.spawn(process_sync)


#: Max time in seconds after a purchase is made before a sync process is launched
SYNC_TIME = 100


def _should_sync(purchase, now=None):
    now = now or time.time()
    start_time = purchase.StartTime
    # CS: SYNC_TIME is the [magic] number of seconds elapsed since the purchase
    # attempt was started. After this time, we try to get the purchase
    # status by asking its payment processor
    result = now - start_time >= SYNC_TIME and not purchase.is_synced()
    return result


class BaseGetPurchaseAttemptView(object):

    def _do_get(self, purchase_id, username=None):
        if not purchase_id:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Must specify a valid purchase attempt id."),
                            'field': 'purchase_id'
                        },
                        None)

        if not username:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Must specify a valid user/creator name."),
                            'field': 'username'
                        },
                        None)

        try:
            purchase = get_purchase_by_code(purchase_id)
            purchase_id = purchase.id if purchase is not None else purchase_id
        except ValueError:
            pass

        purchase = get_purchase_attempt(purchase_id, username)
        if purchase is None:
            raise_error(self.request,
                        hexc.HTTPNotFound,
                        {
                            'message': _(u"Invalid purchase attempt id."),
                            'field': 'purchase_id',
                            'value': purchase_id
                        },
                        None)
        elif purchase.is_pending() and _should_sync(purchase):
            _sync_purchase(purchase, self.request)

        # CS: we return the purchase attempt inside a ITEMS collection
        # due to legacy code
        result = LocatedExternalDict()
        result[ITEMS] = [purchase]
        result[LAST_MODIFIED] = purchase.lastModified
        interface.alsoProvides(result, IUncacheableInResponse)
        result[TOTAL] = result[ITEM_COUNT] = len(result[ITEMS])
        return result


@view_config(name="GetPurchaseAttempt")
@view_config(name="get_purchase_attempt")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='GET')
class GetPurchaseAttemptView(AbstractAuthenticatedView, BaseGetPurchaseAttemptView):

    def __call__(self):
        request = self.request
        username = self.remoteUser.username
        purchase_id = request.subpath[0] if request.subpath else None
        if not purchase_id:
            values = CaseInsensitiveDict(self.request.params)
            purchase_id = values.get('ntiid') \
                       or values.get('purchase') \
                       or values.get('purchaseId')
        result = self._do_get(purchase_id, username)
        return result


@view_config(name="GetGiftPurchaseAttempt")
@view_config(name="get_gift_purchase_attempt")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='GET')
class GetGiftPurchaseAttemptView(AbstractView, BaseGetPurchaseAttemptView):

    def __call__(self):
        values = CaseInsensitiveDict(self.request.params)
        purchase_id = values.get('ntiid') \
                   or values.get('purchase') \
                   or values.get('purchaseId')

        username = values.get('from') \
                or values.get('sender') \
                or values.get('creator') \
                or values.get('username')

        result = self._do_get(purchase_id, username)
        return result


def check_purchasable_access(purchasable, remoteUser=None):
    is_authenticated = (remoteUser is not None)
    return is_authenticated or purchasable.Giftable


@view_config(name="GetPurchasables")
@view_config(name="get_purchasables")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='GET')
class GetPurchasablesView(AbstractAuthenticatedView):

    def _check_access(self, purchasable):
        result = purchasable.isPublic \
            and check_purchasable_access(purchasable, self.remoteUser)
        return result

    def __call__(self):
        values = CaseInsensitiveDict(self.request.params)
        ntiids = values.get("purchasable") or values.get('purchasables')
        if ntiids:
            ntiids = {unquote(x) for x in ntiids.split()}

        purchasables = []
        for p in get_all_purchasables():
            if      self._check_access(p) \
                and (not ntiids or p.NTIID in ntiids):
                purchasables.append(p)
        result = LocatedExternalDict()
        result[ITEMS] = purchasables
        result[TOTAL] = result[ITEM_COUNT] = len(purchasables)
        return result


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             context=IPurchasable,
             request_method='GET')
class PurchasableGetView(GenericGetView):

    def __call__(self):
        result = GenericGetView.__call__(self)
        remote_user = get_remote_user(self.request)
        if      result is not None \
            and not check_purchasable_access(result, remote_user):
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


def _call_pricing_func(func):
    try:
        result = func()
    except InvalidPurchasable:
        result = IPricingError(_("Invalid purchasable."))
    except PricingException as e:
        result = IPricingError(e)
    except Exception:
        raise
    return result


def perform_pricing(purchasable, quantity):
    pricer = component.getUtility(IPurchasablePricer)
    priceable = create_priceable(ntiid=purchasable, quantity=quantity)
    result = pricer.price(priceable)
    return result


@view_config(name="PricePurchasable")
@view_config(name="price_purchasable")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class PricePurchasableView(AbstractPostView):

    def price_purchasable(self, values=None):
        values = values or self.readInput()
        purchasable = values.get('ntiid') \
                   or values.get('purchasable') \
                   or values.get('purchasableId') \
                   or values.get('purchasable_id')

        if not purchasable:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid purchasable ntiid."),
                            'field': 'purchasable'
                        },
                        None)
        # check quantity
        quantity = values.get('quantity', 1)
        if not is_valid_pve_int(quantity):
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid quantity."),
                            'field': 'quantity'
                        },
                        None)
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


@view_config(name="PriceOrder")
@view_config(name="price_order")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class PriceOrderView(AbstractAuthenticatedView, PriceOrderViewMixin):

    procesor = ''

    def _do_pricing(self, order):
        result = _call_pricing_func(partial(price_order, order, self.procesor))
        status = 422 if IPricingError.providedBy(result) else 200
        self.request.response.status_int = status
        return result

    def _do_call(self):
        order = self.readCreateUpdateContentObject()
        assert self.content_predicate(order)
        return self._do_pricing(order)
