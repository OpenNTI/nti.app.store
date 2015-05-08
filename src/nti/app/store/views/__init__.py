#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from urllib import unquote

from zope import interface

from zope.container.contained import Contained

from zope.traversing.interfaces import IPathAdapter

from pyramid import httpexceptions as hexc

from nti.store.purchasable import get_purchasable

from .. import STORE
from .. import PURCHASABLES

@interface.implementer(IPathAdapter)
class StorePathAdapter(Contained):

	__name__ = STORE

	def __init__(self, context, request):
		self.context = context
		self.request = request
		self.__parent__ = context

	def __getitem__(self, key):
		if key == PURCHASABLES:
			return PurchasablesPathAdapter(self, self.request)
		raise KeyError(key)

@interface.implementer(IPathAdapter)
class PurchasablesPathAdapter(Contained):

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
