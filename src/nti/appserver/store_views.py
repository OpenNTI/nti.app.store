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

from pyramid.view import view_config

from nti.dataserver import authorization as nauth

from ..store import pyramid_views
from ..store import get_purchase_attempt
from ..store import interfaces as store_interfaces
from ..store.payments.stripe import interfaces as stripe_interfaces

@component.adapter(store_interfaces.IPurchaseAttemptSuccessful)
def _purchase_attempt_successful(event):
	get_purchase_attempt(event.purchase_id, event.username)
	# TODO: send email

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 context=store_interfaces.IPurchaseAttempt,
			 request_method='GET',
			 name="get_purchase_attempt")
class GetPurchaseAttemptView(pyramid_views.GetPurchaseAttemptView):
	""" Returning a purchase attempt """

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 context=store_interfaces.IPurchaseAttempt,
			 request_method='GET',
			 name="get_pending_purchases")
class GetPendingPurchasesView(pyramid_views.GetPendingPurchasesView):
	""" Return all pending purchases items """

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 context=store_interfaces.IPurchaseAttempt,
			 request_method='GET',
			 name="get_purchase_history")
class GetPurchaseHistoryView(pyramid_views.GetPurchaseHistoryView):
	""" Return purchase history """

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 context=store_interfaces.IPurchasable,
			 request_method='GET',
			 name="get_purchasables")
class GetPurchasablesView(pyramid_views.GetPurchasablesView):
	""" Return all purchasables items """

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 context=stripe_interfaces.IStripeConnectKey,
			 request_method='GET',
			 name="get_stripe_connect_key")
class GetStripeConnectKeyView(pyramid_views.GetStripeConnectKeyView):
	""" Return the stripe connect key """

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 context=store_interfaces.IPurchaseAttempt,
			 request_method='POST',
			 name="post_stripe_payment")
class ProcessPaymentWithStripeView(pyramid_views.StripePaymentView):
	""" Process a payment using stripe """

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 context=store_interfaces.IPurchaseAttempt,
			 request_method='POST',
			 name="validate_stripe_coupon")
class ValidateStripeCouponView(pyramid_views.ValidateStripeCouponView):
	""" Validate a stripe token """
