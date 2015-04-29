#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.container.contained import Contained

from zope.proxy import ProxyBase

from zope.traversing.interfaces import IPathAdapter

from nti.store.purchasable import get_purchasable

from .. import STORE

@interface.implementer(IPathAdapter)
class StorePathAdapter(Contained):

	__name__ = STORE

	def __init__(self, context, request):
		self.context = context
		self.request = request
		self.__parent__ = context

class PurchaseAttemptProxy(ProxyBase):
	
	Items = property(
					lambda s: s.__dict__.get('_v_items'),
					lambda s, v: s.__dict__.__setitem__('_v_items', v))
	
	def __new__(cls, base, *args, **kwargs):
		return ProxyBase.__new__(cls, base)

	def __init__(self, base, items=None):
		ProxyBase.__init__(self, base)
		self.Items = items
		
def get_purchase_purchasables(purchase):
	purchasables = {get_purchasable(x) for x in purchase.Items}
	purchasables.discard(None)
	return purchasables
