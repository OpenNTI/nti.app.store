#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Workspaces / Collections related NTI store

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface
from zope.location import interfaces as loc_interfaces

from nti.appserver import interfaces as app_interfaces

from nti.dataserver import links

from nti.store.course import Course
from nti.store.purchasable import Purchasable

@interface.implementer(app_interfaces.IWorkspace)
@component.adapter(app_interfaces.IUserService)
def _store_workspace(user_service):
    store_ws = StoreWorkspace(parent=user_service.__parent__)
    return store_ws

@interface.implementer(app_interfaces.IWorkspace)
class StoreWorkspace(object):

    links = ()
    __parent__ = None

    def __init__(self, parent=None):
        super(StoreWorkspace, self).__init__()
        if parent:
            self.__parent__ = parent

    @property
    def name(self): return 'store'
    __name__ = name

    @property
    def collections(self):
        return (_StoreCollection(self),)

@interface.implementer(app_interfaces.IContainerCollection)
@component.adapter(app_interfaces.IUserWorkspace)
class _StoreCollection(object):

    name = 'Store'
    __name__ = u''
    __parent__ = None

    def __init__(self, user_workspace):
        self.__parent__ = user_workspace

    @property
    def links(self):
        result = []
        for rel in ('get_purchase_attempt', 'get_pending_purchases', 'get_purchase_history',
                    'get_purchasables', 'get_courses', 'redeem_purchase_code',
                    'create_stripe_token', 'get_stripe_connect_key', 'post_stripe_payment'):
            link = links.Link(rel, rel=rel)
            link.__name__ = link.target
            link.__parent__ = self.__parent__
            interface.alsoProvides(link, loc_interfaces.ILocation)
            result.append(link)
        return result

    @property
    def container(self):
        return ()

    @property
    def accepts(self):
        return (Course.mimeType, Purchasable.mimeType)


