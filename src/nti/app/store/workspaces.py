#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from zope.container.contained import Contained

from zope.location.interfaces import ILocation

from pyramid.threadlocal import get_current_request

from nti.app.invitations.interfaces import IUserInvitationsLinkProvider

from nti.app.store import REGISTERED_STRIPE_KEYS
from nti.app.store import STORE
from nti.app.store import STRIPE
from nti.app.store import PAYEEZY
from nti.app.store import DEFAULT_STRIPE_KEY_ALIAS

from nti.app.store.interfaces import IStoreWorkspace

from nti.appserver.workspaces.interfaces import IUserService
from nti.appserver.workspaces.interfaces import IUserWorkspace
from nti.appserver.workspaces.interfaces import IContainerCollection

from nti.dataserver.authorization import is_site_admin

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserverFolder

from nti.links.links import Link

from nti.property.property import alias

from nti.store.payments.stripe.interfaces import IStripeConnectConfig
from nti.store.payments.stripe.interfaces import IStripeConnectKey

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


@interface.implementer(IStoreWorkspace)
class _StoreWorkspace(Contained):

    __name__ = STORE
    name = alias('__name__', __name__)

    links = ()

    def __init__(self, user_service):
        self.context = user_service
        self.user = user_service.user

    def __getitem__(self, key):
        """
        Make us traversable to collections.
        """
        for i in self.collections:
            if i.__name__ == key:
                return i
        raise KeyError(key)

    def __len__(self):
        return len(self.collections)

    @Lazy
    def collections(self):
        return (_StoreCollection(self),)


@interface.implementer(IStoreWorkspace)
@component.adapter(IUserService)
def StoreWorkspace(user_service):
    workspace = _StoreWorkspace(user_service)
    workspace.__parent__ = workspace.user
    return workspace


@interface.implementer(IContainerCollection)
@component.adapter(IUserWorkspace)
class _StoreCollection(object):

    name = STORE

    __name__ = u''
    __parent__ = None

    def __init__(self, user_workspace):
        self.__parent__ = user_workspace

    @property
    def user(self):
        return self.__parent__.user

    @property
    def root(self):
        request = get_current_request()
        try:
            result = request.path_info_peek() if request else None
        except AttributeError:  # in unit test we may see this
            result = None
        root = result or "dataserver2"
        return root

    def _has_stripe_connect_key(self):
        return bool(component.queryUtility(IStripeConnectKey, name=DEFAULT_STRIPE_KEY_ALIAS))

    @property
    def links(self):
        result = []
        ds_folder = find_interface(self.__parent__,
                                   IDataserverFolder,
                                   strict=False)
        for rel in ('get_purchase_attempt',
                    'get_pending_purchases',
                    'get_purchase_history',
                    'get_purchasables',
                    'redeem_gift',
                    'redeem_purchase_code',
                    'get_gift_pending_purchases',
                    'get_gift_purchase_attempt',
                    'price_purchasable'):
            link = Link(STORE, rel=rel, elements=('@@' + rel,))
            link.__name__ = link.target
            link.__parent__ = ds_folder
            interface.alsoProvides(link, ILocation)
            result.append(link)
        # stripe links
        root = self.root
        href = '/%s/%s/%s' % (root, STORE, STRIPE)
        for rel, name in (('gift_stripe_payment', 'gift_payment'),
                          ('gift_stripe_payment_preflight', 'gift_payment_preflight'),
                          ('price_purchasable_with_stripe_coupon', 'price_purchasable')):
            link = Link(href, rel=rel, elements=('@@' + name,))
            link.__name__ = ''
            interface.alsoProvides(link, ILocation)
            result.append(link)
        # stripe site admin links
        if is_site_admin(self.user):
            if not self._has_stripe_connect_key():
                stripe_connect_config = component.getUtility(IStripeConnectConfig)
                link = Link(stripe_connect_config.StripeOauthEndpoint, rel='connect_stripe_account')
            else:
                link = Link('/%s/%s/%s/%s/@@disconnect_stripe_account' % (root, STORE, STRIPE, REGISTERED_STRIPE_KEYS),
                            rel='disconnect_stripe_account')
                link.__name__ = ''
                interface.alsoProvides(link, ILocation)
            result.append(link)
        # payeezy links
        href = '/%s/%s/%s' % (root, STORE, PAYEEZY)
        for rel, name in (('gift_payeezy_payment', 'gift_payment'),
                          ('gift_payeezy_payment_preflight', 'gift_payment_preflight'),
                          ('price_purchasable_with_payeezy', 'price_purchasable')):
            link = Link(href, rel=rel, elements=('@@' + name,))
            link.__name__ = ''
            interface.alsoProvides(link, ILocation)
            result.append(link)
        return result

    @property
    def container(self):
        return ()

    @property
    def accepts(self):
        return ()


@component.adapter(IUser)
@interface.implementer(IUserInvitationsLinkProvider)
class _RedeemPurchaseCodeInvitationsLinkProvider(object):

    def __init__(self, user=None):
        self.user = user

    def links(self, workspace):
        link = Link(workspace.__parent__,  # IUser
                    method="POST",
                    rel="redeem_purchase_code",
                    elements=('@@redeem_purchase_code',))
        link.__name__ = 'redeem_purchase_code'
        link.__parent__ = workspace.__parent__
        interface.alsoProvides(link, ILocation)
        return (link,)
