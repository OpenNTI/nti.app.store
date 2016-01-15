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

from zope.container.contained import Contained

from zope.location.interfaces import ILocation

from nti.app.store import STORE

from nti.app.store.interfaces import IStoreWorkspace

from nti.appserver.workspaces.interfaces import IUserService
from nti.appserver.workspaces.interfaces import IUserWorkspace
from nti.appserver.workspaces.interfaces import IContainerCollection

from nti.common.property import Lazy
from nti.common.property import alias

from nti.dataserver.interfaces import IDataserverFolder

from nti.links.links import Link

from nti.store.utils import ALL_STORE_MIME_TYPES

from nti.traversal.traversal import find_interface

@interface.implementer(IStoreWorkspace)
class _StoreWorkspace(Contained):

	__name__ = STORE
	name = alias('__name__', __name__)

	links = ()

	def __init__(self, user_service):
		self.context = user_service
		self.user = user_service.user

	def __getitem__(self, key):
		"""
		Make us traversable to collections.
		"""
		for i in self.collections:
			if i.__name__ == key:
				return i
		raise KeyError(key)

	def __len__(self):
		return len(self.collections)

	@Lazy
	def collections(self):
		return (_StoreCollection(self),)

@interface.implementer(IStoreWorkspace)
@component.adapter(IUserService)
def StoreWorkspace(user_service):
	workspace = _StoreWorkspace(user_service)
	workspace.__parent__ = workspace.user
	return workspace

@interface.implementer(IContainerCollection)
@component.adapter(IUserWorkspace)
class _StoreCollection(object):

	name = STORE

	__name__ = u''
	__parent__ = None

	def __init__(self, user_workspace):
		self.__parent__ = user_workspace

	@property
	def links(self):
		result = []
		ds_folder = find_interface(self.__parent__, IDataserverFolder, strict=False)
		for rel in ('get_purchase_attempt',
					'get_pending_purchases',
					'get_purchase_history', 
					'get_purchasables',
					'redeem_purchase_code',
					'redeem_gift',
					'get_gift_pending_purchases',
					'get_gift_purchase_attempt',
					'price_purchasable',
					 # stripe links
					'gift_stripe_payment',
					'gift_stripe_payment_preflight',
					'price_purchasable_with_stripe_coupon'):
			link = Link(STORE, rel=rel, elements=('@@' + rel,))
			link.__name__ = link.target
			link.__parent__ = ds_folder
			interface.alsoProvides(link, ILocation)
			result.append(link)
		return result

	@property
	def container(self):
		return ()

	@property
	def accepts(self):
		mime_types = ALL_STORE_MIME_TYPES
		return mime_types
