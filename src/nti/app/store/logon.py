#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface
from zope import component

from pyramid.interfaces import IRequest

from nti.appserver.interfaces import IMissingUser
from nti.appserver.interfaces import ILogonLinkProvider
from nti.appserver.interfaces import IAuthenticatedUserLinkProvider
from nti.appserver.interfaces import IUnauthenticatedUserLinkProvider

from nti.dataserver.links import Link
from nti.dataserver.interfaces import IUser

from . import STORE

class _BaseStoreLinkProvider(object):

	def __init__(self, request):
		self.request = request
	
	def link_map(self):
		result = {}
		root = self.request.route_path('objects.generic.traversal', traverse=())
		root = root[:-1] if root.endswith('/') else root
		for name in ('get_purchasables',
					 'gift_stripe_payment', 
					 'get_gift_pending_purchases',
					 'get_gift_purchase_attempt',
					 'price_purchasable',
					 ## stripe links
					 'price_purchasable_with_stripe_coupon'):
			elements = (STORE, name)
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

@interface.implementer(ILogonLinkProvider)
@component.adapter(IMissingUser, IRequest)
class _StoreMissingUserLinkProvider(_StoreAuthenticatedUserLinkProvider):
	
	def __call__(self):
		result = self.link_map().get(self.rel)
		return result
	
class _GetGiftPurchaseAttemptMissingUserLinkProvider(_StoreMissingUserLinkProvider):
	rel = 'get_gift_purchase_attempt'
	
class _GiftStripePaymentMissingUserLinkProvider(_StoreMissingUserLinkProvider):
	rel = 'gift_stripe_payment'

class _GetPurchasablesMissingUserLinkProvider(_StoreMissingUserLinkProvider):
	rel = 'get_purchasables'
	
class _GetGiftPendingPurchasesMissingUserLinkProvider(_StoreMissingUserLinkProvider):
	rel = 'get_gift_pending_purchases'

class _PricePurchasableMissingUserLinkProvider(_StoreMissingUserLinkProvider):
	rel = 'price_purchasable'

class _PricePurchasableWithStripeCouponMissingUserLinkProvider(_StoreMissingUserLinkProvider):
	rel = 'price_purchasable_with_stripe_coupon'
