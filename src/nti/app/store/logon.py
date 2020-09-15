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

from pyramid.interfaces import IRequest

from nti.app.store import STORE
from nti.app.store import STRIPE

from nti.appserver.interfaces import IAuthenticatedUserLinkProvider
from nti.appserver.interfaces import IUnauthenticatedUserLinkProvider

from nti.dataserver.interfaces import IUser

from nti.links.links import Link

logger = __import__('logging').getLogger(__name__)


class _BaseStoreLinkProvider(object):

    def __init__(self, request):
        self.request = request

    def link_map(self):
        result = {}
        root = self.request.route_path('objects.generic.traversal',
                                       traverse=())
        root = root[:-1] if root.endswith('/') else root
        for name in ('get_purchasables',
                     'price_purchasable',
                     'get_gift_purchase_attempt',
                     'get_gift_pending_purchases'):
            elements = (STORE, '@@' + name)
            link = Link(root, elements=elements, rel=name)
            result[name] = link
        # stripe links
        for rel, name in (('gift_stripe_payment', 'gift_payment'),
                          ('gift_stripe_payment_preflight',
                           'gift_payment_preflight'),
                          ('price_purchasable_with_stripe_coupon', 'price_purchasable')):
            elements = (STORE, STRIPE, '@@' + name)
            link = Link(root, elements=elements, rel=rel)
            result[rel] = link
        return result

    def get_links(self):
        result = self.link_map().values()
        return list(result)


@component.adapter(IRequest)
@interface.implementer(IUnauthenticatedUserLinkProvider)
class _StoreUnauthenticatedUserLinkProvider(_BaseStoreLinkProvider):
    pass


@component.adapter(IUser, IRequest)
@interface.implementer(IAuthenticatedUserLinkProvider)
class _StoreAuthenticatedUserLinkProvider(_BaseStoreLinkProvider):

    def __init__(self, user, request):
        super(_StoreAuthenticatedUserLinkProvider, self).__init__(request)
        self.user = user
