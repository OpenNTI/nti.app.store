#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.common.property import Lazy

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.interfaces import ALL_PERMISSIONS
from nti.dataserver.interfaces import EVERYONE_USER_NAME

from nti.store.interfaces import IPurchasable

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
