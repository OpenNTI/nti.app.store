#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import urllib

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from zope.container.interfaces import ILocation

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.app.store import STORE
from nti.app.store import STRIPE
from nti.app.store import PAYEEZY
from nti.app.store import PURCHASABLES

from nti.appserver.pyramid_authorization import has_permission

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator

from nti.externalization.externalization import to_external_object

from nti.externalization.singleton import SingletonDecorator

from nti.links.links import Link

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.store.interfaces import IPurchasable
from nti.store.interfaces import IPurchaseItem

from nti.store.payments.payeezy.interfaces import IPayeezyConnectKey

from nti.store.payments.stripe.interfaces import IStripeConnectKey

from nti.store.store import get_purchasable
from nti.store.store import is_item_activated
from nti.store.store import has_history_by_item

ITEMS = StandardExternalFields.ITEMS
LINKS = StandardExternalFields.LINKS


@interface.implementer(IExternalObjectDecorator)
class _BaseRequestAwareDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, context, result):
        return True

    @property
    def ds_store_path(self):
        request = self.request
        try:
            ds2 = request.path_info_peek()
        except AttributeError:  # in unit test we see this
            ds2 = "dataserver2"
        ds_store_path = '/%s/%s/' % (ds2, STORE)
        return ds_store_path


@component.adapter(IPurchasable)
class _PurchasableDecorator(_BaseRequestAwareDecorator):

    def set_links(self, original, external, username=None):
        links = external.setdefault(LINKS, [])
        ds_store_path = self.ds_store_path

        if original.Amount:
            # insert history link
            if username and has_history_by_item(username, original.NTIID):
                history_href = ds_store_path + '@@get_purchase_history'
                quoted = urllib.quote(original.NTIID)
                link = Link(history_href,
                            rel="history",
                            method='GET',
                            params={'ntiid': quoted})
                interface.alsoProvides(link, ILocation)
                links.append(link)

            # insert price link
            for name in ('price', 'price_purchasable'):
                price_href = ds_store_path + '@@price_purchasable'
                link = Link(price_href, rel=name, method='POST')
                interface.alsoProvides(link, ILocation)
                links.append(link)

        if original.Redeemable:
            href = ds_store_path + '@@redeem_gift'
            link = Link(href, rel="redeem_gift", method='POST')
            interface.alsoProvides(link, ILocation)
            links.append(link)

    def add_activation(self, username, original, external):
        activated = is_item_activated(username, original.NTIID)
        external['Activated'] = activated

    def _do_decorate_external(self, original, external):
        if self._is_authenticated:
            username = self.remoteUser.username
            self.add_activation(username, original, external)
        else:
            username = None
        self.set_links(original, external, username)


@component.adapter(IPurchasable)
class _StripePurchasableDecorator(_BaseRequestAwareDecorator):

    def set_links(self, original, external):
        stripe_path = self.ds_store_path + '/' + STRIPE
        links = external.setdefault(LINKS, [])
        quoted = urllib.quote(original.Provider)
        # set common links
        for name, rel, meth in (
                ('create_token', 'create_stripe_token', 'POST'),
                ('get_connect_key', 'get_stripe_connect_key', 'GET'),
                ('price_purchasable', 'price_purchasable_with_stripe_coupon', 'POST')):
            params = {'provider': quoted} if meth == 'GET' else None
            href = stripe_path + '@@' + name
            link = Link(href,
                        rel=rel,
                        method=meth,
                        params=params)
            interface.alsoProvides(link, ILocation)
            links.append(link)
        # set links authenticated users
        if self._is_authenticated:
            href = stripe_path + '@@post_payment'
            link = Link(href, rel="post_stripe_payment", method='POST')
            interface.alsoProvides(link, ILocation)
            links.append(link)
        # set links giftable objects
        if original.Giftable:
            href = stripe_path + '@@gift_payment'
            link = Link(href, rel="gift_stripe_payment", method='POST')
            interface.alsoProvides(link, ILocation)
            links.append(link)

    def _do_decorate_external(self, original, external):
        keyname = original.Provider
        result = component.queryUtility(IStripeConnectKey, keyname)
        if result is not None and original.Amount:
            self.set_links(original, external)
            external['StripeConnectKey'] = to_external_object(result)


@component.adapter(IPurchasable)
class _PayeezyPurchasableDecorator(_BaseRequestAwareDecorator):

    def set_links(self, original, external):
        payeezy_path = self.ds_store_path + '/' + PAYEEZY
        links = external.setdefault(LINKS, [])
        quoted = urllib.quote(original.Provider)
        # set common links
        for name, rel, meth in (
                ('create_token', 'create_payeezy_token', 'POST'),
                ('get_connect_key', 'get_payeezy_connect_key', 'GET'),
                ('price_purchasable', 'price_purchasable_with_payeezy', 'POST')):
            params = {'provider': quoted} if meth == 'GET' else None
            href = payeezy_path + '@@' + name
            link = Link(href,
                        rel=rel,
                        method=meth,
                        params=params)
            interface.alsoProvides(link, ILocation)
            links.append(link)
        # set links authenticated users
        if self._is_authenticated:
            href = payeezy_path + '@@post_payment'
            link = Link(href, rel="post_payeezy_payment", method='POST')
            interface.alsoProvides(link, ILocation)
            links.append(link)
        # set links giftable objects
        if original.Giftable:
            href = payeezy_path + '@@gift_payment'
            link = Link(href, rel="gift_stripe_payment", method='POST')
            interface.alsoProvides(link, ILocation)
            links.append(link)

    def _do_decorate_external(self, original, external):
        keyname = original.Provider
        result = component.queryUtility(IPayeezyConnectKey, keyname)
        if result is not None and original.Amount:
            self.set_links(original, external)


@component.adapter(IPurchasable)
@interface.implementer(IExternalObjectDecorator)
class _PurchasableEditionLinksDecorator(_BaseRequestAwareDecorator):

    @Lazy
    def _acl_decoration(self):
        result = getattr(self.request, 'acl_decoration', True)
        return result

    def _has_edit_link(self, result):
        for lnk in result.get(LINKS) or ():
            if getattr(lnk, 'rel', None) == 'edit':
                return True
        return False

    def _predicate(self, context, result):
        return (    self._acl_decoration
                and self._is_authenticated
                and has_permission(ACT_CONTENT_EDIT, context, self.request))

    def _do_decorate_external(self, context, result):
        _links = []
        ntiid = urllib.quote(context.NTIID)
        path = self.ds_store_path + '/' + PURCHASABLES + '/' + ntiid

        # enable / disable link
        rel = 'disable' if context.isPublic() else 'enable'
        link = Link(path + '/@@' + rel, rel=rel, method='POST')
        _links.append(link)

        # edit link
        if not self._has_edit_link(result):
            link = Link(path, rel='edit', method='POST')
            _links.append(link)

        for link in _links:
            interface.alsoProvides(link, ILocation)
            link.__name__ = ''
            link.__parent__ = context
            result.setdefault(LINKS, []).append(link)


@component.adapter(IPurchaseItem)
@interface.implementer(IExternalObjectDecorator)
class _PurchaseItemDecorator(object):

    __metaclass__ = SingletonDecorator

    def decorateExternalObject(self, original, external):
        purchasable = get_purchasable(original.NTIID)
        if purchasable:
            external[ITEMS] = items = []
            for item in purchasable.Items:
                item = find_object_with_ntiid(item)
                if item is not None:
                    item = to_external_object(item)
                    items.append(item)
