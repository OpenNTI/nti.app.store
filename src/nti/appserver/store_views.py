#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views and other objects relating to NTI store

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface
from zope.traversing.interfaces import IPathAdapter
from zope.location.interfaces import IContained

from pyramid.view import view_config

from nti.dataserver import authorization as nauth

from nti.store import pyramid_views
from nti.store import interfaces as store_interfaces

@interface.implementer(IPathAdapter, IContained)
class StorePathAdapter(object):
	"""
	Exists to provide a namespace in which to place all of these views,
	and perhaps to traverse further on.
	"""

	__parent__ = None
	__name__ = None

	def __init__(self, context, request):
		self.context = context
		self.request = request

@component.adapter(store_interfaces.IPurchaseAttemptSuccessful)
def _purchase_attempt_successful(event):
	pass
	# TODO: send email


_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=StorePathAdapter,
					  request_method='GET')
_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

@view_config(name="get_purchase_attempt", **_view_defaults)
class GetPurchaseAttemptView(pyramid_views.GetPurchaseAttemptView):
	""" Returning a purchase attempt """""

@view_config(name="get_pending_purchases", **_view_defaults)
class GetPendingPurchasesView(pyramid_views.GetPendingPurchasesView):
	""" Return all pending purchases items """

@view_config(name="get_purchase_history", **_view_defaults)
class GetPurchaseHistoryView(pyramid_views.GetPurchaseHistoryView):
	""" Return purchase history """

@view_config(name="get_purchasables", **_view_defaults)
class GetPurchasablesView(pyramid_views.GetPurchasablesView):
	""" Return all purchasables items """

@view_config(name="create_stripe_token", **_post_view_defaults)
class CreateStripeTokenView(pyramid_views.CreateStripeTokenView):
	""" Create a stripe payment token """

@view_config(name="get_stripe_connect_key", **_view_defaults)
class GetStripeConnectKeyView(pyramid_views.GetStripeConnectKeyView):
	""" Return the stripe connect key """

@view_config(name="post_stripe_payment", **_post_view_defaults)
class ProcessPaymentWithStripeView(pyramid_views.StripePaymentView):
	""" Process a payment using stripe """

@view_config(name="price_purchasable", **_post_view_defaults)
class PricePurchasableView(pyramid_views.PricePurchasableView):
	""" price purchaseable """

@view_config(name="price_purchasable_with_stripe_coupon", **_post_view_defaults)
class PricePurchasableWithStripeCouponView(pyramid_views.PricePurchasableWithStripeCouponView):
	""" price purchaseable with a stripe token """

@view_config(name="redeem_purchase_code", **_post_view_defaults)
class RedeemPurchaseCodeView(pyramid_views.RedeemPurchaseCodeView):
	""" redeem a purchase code """

del _view_defaults
del _post_view_defaults


