#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import interface

from nti.app.store.interfaces import ISiteLicenseStorePolicy


@interface.implementer(ISiteLicenseStorePolicy)
class TrialSiteLicenseStorePolicy(object):

    def can_use_coupons(self):
        return False

    def can_create_purchasable(self):
        return False

    def can_integrate(self):
        return False


@interface.implementer(ISiteLicenseStorePolicy)
class StarterSiteLicenseStorePolicy(TrialSiteLicenseStorePolicy):

    def can_create_purchasable(self):
        return True
    can_integrate = can_create_purchasable


@interface.implementer(ISiteLicenseStorePolicy)
class GrowthSiteLicenseStorePolicy(StarterSiteLicenseStorePolicy):

    def can_use_coupons(self):
        return True

EnterpriseSiteLicenseStorePolicy = GrowthSiteLicenseStorePolicy

