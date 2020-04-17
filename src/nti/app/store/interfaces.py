#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import interface

from nti.app.products.integration.interfaces import IIntegration

from nti.appserver.workspaces.interfaces import IWorkspace


class IStoreWorkspace(IWorkspace):
    """
    A workspace containing data for store.
    """


class IPurchasableDefaultFieldProvider(interface.Interface):
    """
    A utility that will provide some basic default fields for use
    when a new purchasable is created via the API.
    """

    def get_default_fee():
        pass

    def get_default_provider():
        pass

    def get_default_currency():
        pass


class IStripeIntegration(IIntegration):
    """
    Stripe integration
    """


class ISiteLicenseStorePolicy(interface.Interface):
    """
    The policy determining store usage based on the current site license.
    """

    def can_integrate():
        """
        Returns a bool whether or not we can integrate with a store
        provider.
        """

    def can_create_purchasable():
        """
        Returns a bool whether or not a purchasable can be created.
        """

    def can_use_coupons():
        """
        Returns a bool whether or not coupons can be used. This includes
        purchase time.
        """
