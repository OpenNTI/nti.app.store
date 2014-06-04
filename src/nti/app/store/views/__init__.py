#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views and other objects relating to NTI store

.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope import interface
from zope.location.interfaces import IContained
from zope.container import contained as zcontained
from zope.traversing.interfaces import IPathAdapter

from pyramid.view import view_config

from nti.appserver.dataserver_pyramid_views import _GenericGetView as GenericGetView

from nti.dataserver import authorization as nauth

from nti.store import views

@interface.implementer(IPathAdapter, IContained)
class StorePathAdapter(zcontained.Contained):
	"""
	Exists to provide a namespace in which to place all of these views,
	and perhaps to traverse further on.
	"""

	__name__ = 'store'

	def __init__(self, context, request):
		self.context = context
		self.__parent__ = context
		self.request = request

_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=StorePathAdapter,
					  request_method='GET')
_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

_admin_view_defaults = _post_view_defaults.copy()
_admin_view_defaults['permission'] = nauth.ACT_MODERATE

@view_config(name="get_purchase_attempt", **_view_defaults)
class GetPurchaseAttemptView(views.GetPurchaseAttemptView):
	""" Returning a purchase attempt """""

@view_config(name="get_pending_purchases", **_view_defaults)
class GetPendingPurchasesView(views.GetPendingPurchasesView):
	""" Return all pending purchases items """

@view_config(name="get_purchase_history", **_view_defaults)
class GetPurchaseHistoryView(views.GetPurchaseHistoryView):
	""" Return purchase history """

@view_config(name="get_purchasables", **_view_defaults)
class GetPurchasablesView(views.GetPurchasablesView):
	""" Return all purchasables items """

@view_config(name="get_courses", **_view_defaults)
class GetCoursesView(views.GetCoursesView):
	""" Return all course items """

@view_config(name="price_purchasable", **_post_view_defaults)
class PricePurchasableView(views.PricePurchasableView):
	""" price purchaseable """

@view_config(name="redeem_purchase_code", **_post_view_defaults)
class RedeemPurchaseCodeView(views.RedeemPurchaseCodeView):
	""" redeem a purchase code """

@view_config(name="enroll_course", **_post_view_defaults)
class EnrollCourseView(views.EnrollCourseView):
	""" enroll a course """

@view_config(name="unenroll_course", **_post_view_defaults)
class UnenrollCourseView(views.UnenrollCourseView):
	""" unenroll a course """

# stripe

@view_config(name="get_stripe_connect_key", **_view_defaults)
class GetStripeConnectKeyView(views.GetStripeConnectKeyView):
	""" Return the stripe connect key """

@view_config(name="create_stripe_token", **_post_view_defaults)
class CreateStripeTokenView(views.CreateStripeTokenView):
	""" Create a stripe payment token """

@view_config(name="price_purchasable_with_stripe_coupon", **_post_view_defaults)
class PricePurchasableWithStripeCouponView(views.PricePurchasableWithStripeCouponView):
	""" price purchaseable with a stripe token """

@view_config(name="post_stripe_payment", **_post_view_defaults)
class ProcessPaymentWithStripeView(views.StripePaymentView):
	""" Process a payment using stripe """

# object get views

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context='nti.store.interfaces.IPurchasable',
			 permission=nauth.ACT_READ,
			 request_method='GET')
class PurchasableGetView(GenericGetView):
	pass

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context='nti.store.interfaces.IPurchaseAttempt',
			 permission=nauth.ACT_READ,
			 request_method='GET')
class PurchaseAttemptGetView(GenericGetView):

	def __call__(self):
		purchase = super(PurchaseAttemptGetView, self).__call__()
		if purchase.is_pending():
			start_time = purchase.StartTime
			if time.time() - start_time >= 90 and not purchase.is_synced():
				views._sync_purchase(purchase)
		return purchase

del _view_defaults
del _post_view_defaults
del _admin_view_defaults
