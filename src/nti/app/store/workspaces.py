#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Workspaces / Collections related NTI store

.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface
from zope.container import contained
from zope.location import interfaces as loc_interfaces

from nti.appserver import interfaces as app_interfaces

from nti.dataserver import links

from nti.store.course import Course
from nti.store.purchasable import Purchasable
from nti.store.purchase_attempt import PurchaseAttempt

from nti.utils.property import Lazy
from nti.utils.property import alias

from . import STORE
from . import interfaces

@interface.implementer(interfaces.IStoreWorkspace)
class _StoreWorkspace(contained.Contained):

	__name__ = STORE
	name = alias('__name__', __name__)

	links = ()

	def __init__(self, user_service):
		self.context = user_service
		self.user = user_service.user

	def __getitem__(self, key):
		"Make us traversable to collections."
		for i in self.collections:
			if i.__name__ == key:
				return i
		raise KeyError(key)

	def __len__(self):
		return len(self.collections)

	@Lazy
	def collections(self):
		return (_StoreCollection(self),)

@interface.implementer(interfaces.IStoreWorkspace)
@component.adapter(app_interfaces.IUserService)
def StoreWorkspace(user_service):
	workspace = _StoreWorkspace(user_service)
	workspace.__parent__ = workspace.user
	return workspace

@interface.implementer(app_interfaces.IContainerCollection)
@component.adapter(app_interfaces.IUserWorkspace)
class _StoreCollection(object):

	name = STORE
	__name__ = u''
	__parent__ = None

	def __init__(self, user_workspace):
		self.__parent__ = user_workspace

	@property
	def links(self):
		result = []
		for rel in ('get_purchase_attempt', 'get_pending_purchases',
					'get_purchase_history', 'get_purchasables', 'get_courses',
					'redeem_purchase_code', 'create_stripe_token',
					'get_stripe_connect_key', 'post_stripe_payment',
					'refund_stripe_payment'):
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
		return (getattr(Course, 'mimeType', getattr(Course, 'mime_type')),
				getattr(Purchasable, 'mimeType', getattr(Purchasable, 'mime_type')),
				PurchaseAttempt.mimeType)

