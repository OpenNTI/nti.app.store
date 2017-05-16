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

from nti.appserver.policies.interfaces import ISitePolicyUserEventListener

from nti.site.site import getSite

from nti.store.interfaces import IStorePurchaseMetadataProvider


@interface.implementer(IStorePurchaseMetadataProvider)
class SitePurchaseMetadataProvider(object):
    """
    Augment the purchase metadata with site information.
    """

    def update_metadata(self, data):
        data = data if data else {}
        data['Site'] = getattr(getSite(), '__name__', None)
        policy = component.getUtility(ISitePolicyUserEventListener)
        site_display = getattr(policy, 'BRAND', '')
        site_alias = getattr(policy, 'COM_ALIAS', '')
        # We are inhereting the NT brand, try to use alias.
        if site_display == 'NextThought' and site_alias:
            site_display = site_alias
        data['SiteName'] = site_display
        return data
