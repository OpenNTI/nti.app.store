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

from pyramid.interfaces import IRequest

from nti.appserver.interfaces import IAuthenticatedUserLinkProvider
from nti.appserver.interfaces import IUnauthenticatedUserLinkProvider

from nti.dataserver.interfaces import IUser

from nti.links.links import Link

from . import STORE

class _BaseStoreLinkProvider(object):

	def __init__(self, request):
		self.request = request

	def link_map(self):
		result = {}
		root = self.request.route_path('objects.generic.traversal', traverse=())
		root = root[:-1] if root.endswith('/') else root
		for name in ('get_purchasables',
					 'price_purchasable',
					 'get_gift_purchase_attempt',
					 'get_gift_pending_purchases',
					  # stripe links
					 'gift_stripe_payment',
					 'gift_stripe_payment_preflight',
					 'price_purchasable_with_stripe_coupon'):
			elements = (STORE, '@@' + name)
			link = Link(root, elements=elements, rel=name)
			result[name] = link
		return result

	def get_links(self):
		result = self.link_map().values()
		return list(result)

@interface.implementer(IUnauthenticatedUserLinkProvider)
@component.adapter(IRequest)
class _StoreUnauthenticatedUserLinkProvider(_BaseStoreLinkProvider):
	pass

@interface.implementer(IAuthenticatedUserLinkProvider)
@component.adapter(IUser, IRequest)
class _StoreAuthenticatedUserLinkProvider(_BaseStoreLinkProvider):

	def __init__(self, user, request):
		super(_StoreAuthenticatedUserLinkProvider, self).__init__(request)
		self.user = user
