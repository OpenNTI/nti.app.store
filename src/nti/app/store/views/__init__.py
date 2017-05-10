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
from zope.component.hooks import site as current_site

from zope.location.interfaces import IContained

from zope.traversing.interfaces import IPathAdapter

from pyramid import httpexceptions as hexc

from nti.app.store import STORE
from nti.app.store import STRIPE
from nti.app.store import PURCHASABLES

from nti.dataserver.interfaces import IDataserver

from nti.site.site import get_site_for_site_names

from nti.site.transient import TrivialSite

from nti.store.purchasable import get_purchasable


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
        raise KeyError(key)


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


def dataserver_folder():
    dataserver = component.getUtility(IDataserver)
    return dataserver.root_folder['dataserver2']


def get_job_site(job_site_name=None):
    old_site = getSite()
    if job_site_name is None:
        job_site = old_site
    else:
        ds_folder = dataserver_folder()
        with current_site(ds_folder):
            job_site = get_site_for_site_names((job_site_name,))
        # validate site
        if job_site is None or isinstance(job_site, TrivialSite):
            raise ValueError('No site found for (%s)' % job_site_name)
    return job_site
