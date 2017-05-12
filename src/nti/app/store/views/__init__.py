#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from urllib import unquote

from zope import component
from zope import interface

from zope.component.hooks import getSite

from zope.location.interfaces import IContained

from zope.traversing.interfaces import IPathAdapter

from pyramid import httpexceptions as hexc

from nti.app.store import STORE
from nti.app.store import STRIPE
from nti.app.store import PAYEEZY
from nti.app.store import PURCHASABLES

from nti.store.purchasable import get_purchasable


@interface.implementer(IPathAdapter, IContained)
class PurchasablesPathAdapter(object):

    def __init__(self, parent, request):
        self.request = request
        self.__parent__ = parent
        self.__name__ = PURCHASABLES

    def __getitem__(self, ntiid):
        if not ntiid:
            raise hexc.HTTPNotFound()

        ntiid = unquote(ntiid)
        result = get_purchasable(ntiid)
        if result is not None:
            return result
        raise KeyError(ntiid)


@interface.implementer(IPathAdapter, IContained)
class StripePathAdapter(object):

    def __init__(self, parent, request):
        self.request = request
        self.__parent__ = parent
        self.__name__ = STRIPE


@interface.implementer(IPathAdapter, IContained)
class PayeezyPathAdapter(object):

    def __init__(self, parent, request):
        self.request = request
        self.__parent__ = parent
        self.__name__ = PAYEEZY


@interface.implementer(IPathAdapter, IContained)
class StorePathAdapter(object):

    __name__ = STORE

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.__parent__ = context

    def __getitem__(self, key):
        if key == PURCHASABLES:
            return PurchasablesPathAdapter(self, self.request)
        elif key == STRIPE:
            return StripePathAdapter(self, self.request)
        elif key == PAYEEZY:
            return PayeezyPathAdapter(self, self.request)
        raise KeyError(key)


def get_current_site():
    return getattr(getSite(), '__name__', None)
