#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import


from nti.app.store.interfaces import ISiteLicenseStorePolicy

from nti.site_license.utils import get_site_license_feature_policy


def can_integrate():
    """
    Uses the site license to determine whether this site can integrate
    with a store provider.
    """
    result = True
    policy = get_site_license_feature_policy(ISiteLicenseStorePolicy)
    if policy is not None:
        result = policy.can_integrate()
    return result


def can_create_purchasable():
    """
    Uses the site license to determine whether this site can add
    create new purchasables.
    """
    result = True
    policy = get_site_license_feature_policy(ISiteLicenseStorePolicy)
    if policy is not None:
        result = policy.can_create_purchasable()
    return result


def can_use_coupons():
    """
    Uses the site license to determine whether this site can use
    coupons. This will include when purchases are made.
    """
    result = True
    policy = get_site_license_feature_policy(ISiteLicenseStorePolicy)
    if policy is not None:
        result = policy.can_use_coupons()
    return result
