#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Workspaces / Collections related NTI store

$Id: store_views.py 21508 2013-07-30 03:37:46Z carlos.sanchez $
"""
from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.appserver import interfaces as app_interfaces

@interface.implementer(app_interfaces.IContainerCollection)
@component.adapter(app_interfaces.IUserWorkspace)
class _UserStoreCollection(object):

    name = 'Store'
    __name__ = name
    __parent__ = None

    def __init__(self, user_workspace):
        self.__parent__ = user_workspace

    @property
    def container(self):
        return  ()

    @property
    def accepts(self):
        return ()

@interface.implementer(app_interfaces.IContainerCollection)
@component.adapter(app_interfaces.IUserWorkspace)
def _UserStoreCollectionFactory(workspace):
    return _UserStoreCollection(workspace)
