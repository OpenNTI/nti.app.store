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

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.interfaces import ALL_PERMISSIONS
from nti.dataserver.interfaces import EVERYONE_USER_NAME

from nti.store.interfaces import IPurchasable

from nti.store.payments.stripe.interfaces import IStripeConnectKeyContainer

logger = __import__('logging').getLogger(__name__)


@component.adapter(IPurchasable)
@interface.implementer(IACLProvider)
class PurchasableACLProvider(object):

    def __init__(self, context):
        self.context = context

    @Lazy
    def __acl__(self):
        aces = [ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, type(self)),
                ace_allowing(ROLE_CONTENT_ADMIN, ALL_PERMISSIONS, type(self))]
        if self.context.isPublic():
            aces.append(ace_allowing(EVERYONE_USER_NAME, ACT_READ, type(self)))
        result = acl_from_aces(aces)
        return result


@component.adapter(IStripeConnectKeyContainer)
@interface.implementer(IACLProvider)
class StripeConnectKeyContainerACLProvider(object):

    def __init__(self, context):
        self.context = context

    @Lazy
    def __acl__(self):
        return acl_from_aces([ACE_DENY_ALL])
