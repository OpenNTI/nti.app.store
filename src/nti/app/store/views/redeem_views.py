#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.event import notify

from zope.proxy import ProxyBase

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.store import MessageFactory as _

from nti.app.store.utils import to_boolean
from nti.app.store.utils import AbstractPostView

from nti.app.store.views import StorePathAdapter

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser

from nti.externalization.proxy import removeAllProxies

from nti.invitations.interfaces import IInvitationsContainer

from nti.invitations.utils import accept_invitation

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.store.store import get_purchase_by_code

from nti.store.interfaces import IPriceable
from nti.store.interfaces import IPurchasable
from nti.store.interfaces import IPurchaseOrder
from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IRedemptionError
from nti.store.interfaces import IObjectTransformer
from nti.store.interfaces import IGiftPurchaseAttempt
from nti.store.interfaces import IPurchasableChoiceBundle
from nti.store.interfaces import IInvitationPurchaseAttempt
from nti.store.interfaces import GiftPurchaseAttemptRedeemed

from nti.store.invitations import InvitationExpired
from nti.store.invitations import InvitationAlreadyAccepted
from nti.store.invitations import InvitationCapacityExceeded
from nti.store.invitations import create_store_purchase_invitation

from nti.store.store import get_purchase_attempt
from nti.store.store import get_purchase_purchasables

GENERIC_GIFT_ERROR_MESSAGE = _(u"Gift/Invitation not found.")


def find_redeemable_purchase(code):
    try:
        purchase = get_purchase_by_code(code)
    except ValueError:
        purchase = None
    return purchase


@interface.implementer(IPriceable)
class PurchaseItemProxy(ProxyBase):

    NTIID = property(lambda s: s.__dict__.get('_v_ntiid'),
                     lambda s, v: s.__dict__.__setitem__('_v_ntiid', v))

    def __new__(cls, base, *args, **kwargs):
        return ProxyBase.__new__(cls, base)

    def __init__(self, base, ntiid=None):
        ProxyBase.__init__(self, base)
        self.NTIID = ntiid


@interface.implementer(IPurchaseOrder)
class PurchaseOrderProxy(ProxyBase):

    Items = property(lambda s: s.__dict__.get('_v_items'),
                     lambda s, v: s.__dict__.__setitem__('_v_items', v))

    def __new__(cls, base, *args, **kwargs):
        return ProxyBase.__new__(cls, base)

    def __init__(self, base, items=()):
        ProxyBase.__init__(self, base)
        self.Items = items

    @property
    def NTIIDs(self):
        result = tuple(x.NTIID for x in self.Items)
        return result


@interface.implementer(IPurchaseAttempt)
class PurchaseAttemptProxy(ProxyBase):

    Order = property(lambda s: s.__dict__.get('_v_order'),
                     lambda s, v: s.__dict__.__setitem__('_v_order', v))

    def __new__(cls, base, *args, **kwargs):
        return ProxyBase.__new__(cls, base)

    def __init__(self, base, order=None):
        ProxyBase.__init__(self, base)
        self.Order = order

    @property
    def Items(self):
        return self.Order.NTIIDs


def _proxy_purchase(purchase, *ntiids):
    items = []
    for idx, item in enumerate(purchase.Order.Items):
        proxy = PurchaseItemProxy(item, ntiids[idx])
        items.append(proxy)
    order = PurchaseOrderProxy(purchase.Order, items)
    result = PurchaseAttemptProxy(purchase, order)
    return result


def redeem_invitation_purchase(user, code, purchasable,
                               vendor_updates=None, request=None):
    purchase = find_redeemable_purchase(code)
    if not IInvitationPurchaseAttempt.providedBy(purchase):
        raise hexc.HTTPNotFound(detail=_(u'Purchase attempt not found.'))

    if purchasable not in purchase.Items:
        # Sometimes clients sent the the item being purchased.
        purchasables = get_purchase_purchasables(purchase)
        if len(purchasables) != 1 or purchasable not in purchasables[0].Items:
            msg = _(u"The code is not for this purchasable.")
            raise hexc.HTTPUnprocessableEntity(msg)

    try:
        # create and register the store invitation
        invite = create_store_purchase_invitation(purchase, receiver=user)
        invitations = component.getUtility(IInvitationsContainer)
        invitations.add(invite)

        # process acceptance
        accept_invitation(user, invite)

        # return redeemed purchase attempt
        purchase_id = purchase.get_linked_purchase_id(user)
        purchase = get_purchase_attempt(purchase_id)

        # set vendor updates
        if vendor_updates is not None:
            purchase.Context['AllowVendorUpdates'] = vendor_updates
    except InvitationAlreadyAccepted:
        msg = _(u"The invitation code has already been accepted.")
        raise hexc.HTTPUnprocessableEntity(msg)
    except InvitationCapacityExceeded:
        msg = _(u"There are no remaining invitations for this code.")
        raise hexc.HTTPUnprocessableEntity(msg)
    except InvitationExpired:
        msg = _(u"This invitation is expired.")
        raise hexc.HTTPUnprocessableEntity(msg)
    return purchase


def redeem_gift_purchase(user, code, item=None, vendor_updates=None, request=None):
    purchase = find_redeemable_purchase(code)
    if IInvitationPurchaseAttempt.providedBy(purchase):  # legacy cases
        return redeem_invitation_purchase(user, code,
                                          request=request,
                                          purchasable=item,
                                          vendor_updates=vendor_updates)

    if not IGiftPurchaseAttempt.providedBy(purchase):
        raise hexc.HTTPNotFound(detail=_(u'Purchase attempt not found.'))

    if purchase.is_redeemed():
        msg = _(u"Gift purchase already redeemed.")
        raise hexc.HTTPUnprocessableEntity(msg)

    # set vendor updates before called notify
    if vendor_updates is not None:
        purchase.Context['AllowVendorUpdates'] = vendor_updates

    purchasables = get_purchase_purchasables(purchase)
    if not purchasables:
        msg = _(u"There is nothing to redeem for gift.")
        raise hexc.HTTPUnprocessableEntity(msg)
    elif len(purchase.Items) != len(purchasables):
        msg = _(u"Purchase contains missing purchasables.")
        raise hexc.HTTPUnprocessableEntity(msg)
    elif len(purchasables) == 1:  # check for bundle choice
        purchasable = purchasables.__iter__().next()
        if IPurchasableChoiceBundle.providedBy(purchasable):
            if not item:
                msg = _(u"Must specify a redeemable item.")
                raise hexc.HTTPUnprocessableEntity(msg)
            if item not in purchasable.Items:
                msg = GENERIC_GIFT_ERROR_MESSAGE
                raise hexc.HTTPUnprocessableEntity(msg)
            # find the source object
            source = find_object_with_ntiid(item)
            purchasable = IPurchasable(source)
            # proxy the purchase so change purchase order to include
            # the correct purchasable
            purchase = _proxy_purchase(purchase, purchasable.NTIID)
        elif item and item not in purchasable.Items:
            msg = GENERIC_GIFT_ERROR_MESSAGE
            raise hexc.HTTPUnprocessableEntity(msg)
    notify(GiftPurchaseAttemptRedeemed(purchase, user, code=code, request=request))
    return purchase


def _id(o, *args, **kwargs):
    return o


def _transform_object(obj, user, request=None):
    try:
        transformer = component.queryMultiAdapter((request, obj),
                                                  IObjectTransformer)
        if transformer is None:
            transformer = component.queryAdapter(obj,
                                                 IObjectTransformer,
                                                 default=_id)
        result = transformer(obj, user)
        return result
    except Exception:
        logger.warn("Failed to transform incoming object", exc_info=True)
        return obj


@view_config(name="RedeemPurchaseCode")
@view_config(name="redeem_purchase_code")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               context=StorePathAdapter,
               permission=nauth.ACT_READ)
class RedeemPurchaseCodeView(AbstractPostView):

    def __call__(self):
        values = self.readInput()
        purchasable = values.get('ntiid') \
                   or values.get('purchasable') \
                   or values.get('purchasableId')
        if not purchasable:
            msg = _(u"Must specify a valid purchasable id.")
            raise hexc.HTTPUnprocessableEntity(msg)

        invitation_code = values.get('code') \
                       or values.get('invitation') \
                       or values.get('invitationCode')
        if not invitation_code:
            msg = _(u"Must specify a valid invitation code.")
            raise hexc.HTTPUnprocessableEntity(msg)

        purchase = redeem_invitation_purchase(self.remoteUser,
                                              invitation_code,
                                              purchasable=purchasable,
                                              request=self.request)
        return purchase


@view_config(name="RedeemPurchaseCode")
@view_config(name="redeem_purchase_code")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               context=IUser,
               permission=nauth.ACT_READ)
class UserRedeemPurchaseCodeView(RedeemPurchaseCodeView):
    pass


@view_config(name="RedeemGift")
@view_config(name="redeem_gift")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               context=StorePathAdapter,
               permission=nauth.ACT_READ)
class RedeemGiftView(AbstractPostView):

    def __call__(self):
        values = self.readInput()
        gift_code = values.get('code') \
                 or values.get('gift') \
                 or values.get('giftCode')
        if not gift_code:
            msg = _(u"Must specify a valid gift code.")
            raise hexc.HTTPUnprocessableEntity(msg)

        allow_vendor_updates = values.get('AllowVendorUpdates') \
           					or values.get('allow_vendor_updates')
        if allow_vendor_updates is not None:
            allow_vendor_updates = to_boolean(allow_vendor_updates)

        item = values.get('purchasable') \
            or values.get('item') \
        	or values.get('ntiid')
        try:
            result = redeem_gift_purchase(self.remoteUser,
                                          gift_code,
                                          item=item,
                                          request=self.request,
                                          vendor_updates=allow_vendor_updates)
            result = _transform_object(result, self.remoteUser, self.request)
            result = removeAllProxies(result)  # remove all proxies
        except hexc.HTTPNotFound:
            self.request.response.status_int = 404
            result = IRedemptionError(_(u'Gift/Invitation not found.'))
        except hexc.HTTPUnprocessableEntity as e:
            result = IRedemptionError(e.detail)
            self.request.response.status_int = 422
        except ValueError as e:
            result = IRedemptionError(e)
            self.request.response.status_int = 409
        return result
