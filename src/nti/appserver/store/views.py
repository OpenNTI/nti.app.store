#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views and other objects relating to NTI store

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time
import isodate
import datetime

from zope import component
from zope import interface
from zope.location.interfaces import IContained
from zope.container import contained as zcontained
from zope.traversing.interfaces import IPathAdapter
from zope.publisher.interfaces.browser import IBrowserRequest

from pyramid.view import view_config
from pyramid.threadlocal import get_current_request

from nti.appserver import MessageFactory as _
from nti.appserver._email_utils import queue_simple_html_text_email
from nti.appserver.dataserver_pyramid_views import _GenericGetView as GenericGetView

from nti.dataserver import authorization as nauth
from nti.dataserver.users import interfaces as user_interfaces

from nti.externalization.externalization import to_external_object

from nti.store import invitations
from nti.store import pyramid_views
from nti.store import interfaces as store_interfaces

def _send_purchase_confirmation(event, email):

	# Can only do this in the context of a user actually
	# doing something; we need the request for locale information
	# as well as URL information.
	request = getattr(event, 'request', get_current_request())
	if not request or not email:
		return

	purchase = event.object
	user = purchase.creator
	profile = user_interfaces.IUserProfile(user)

	user_ext = to_external_object(user)
	informal_username = user_ext.get('NonI18NFirstName', profile.realname) or user.username

	# Provide functions the templates can call to format currency values
	currency = component.getAdapter( event, IPathAdapter, name='currency' )

	args = {'profile': profile,
			'context': event,
			'user': user,
			'format_currency': currency.format_currency_object,
			'format_currency_attribute': currency.format_currency_attribute,
			'discount': - (event.purchase.Pricing.TotalNonDiscountedPrice - event.purchase.Pricing.TotalPurchasePrice),
			'transaction_id': invitations.get_invitation_code(purchase),  # We use invitation code as trx id
			'informal_username': informal_username,
			'billed_to': event.charge.Name or profile.realname or informal_username,
			'today': isodate.date_isoformat(datetime.datetime.now()) }

	mailer = queue_simple_html_text_email
	mailer('purchase_confirmation_email',
			subject=_("Purchase Confirmation"),
			recipients=[email],
			template_args=args,
			request=request,
			text_template_extension='.mak')

def safe_send_purchase_confirmation(event, email):
	try:
		_send_purchase_confirmation(event, email)
	except Exception:
		logger.exception("Error while sending purchase confirmation email to %s", email)

@component.adapter(store_interfaces.IPurchaseAttemptSuccessful)
def _purchase_attempt_successful(event):
	# If we reach this point, it means the charge has already gone through
	# don't fail the transaction if there is an error sending
	# the purchase confirmation email
	profile = user_interfaces.IUserProfile(event.object.creator)
	email = getattr(profile, 'email')
	safe_send_purchase_confirmation(event, email)

@interface.implementer(IPathAdapter, IContained)
class StorePathAdapter(zcontained.Contained):
	"""
	Exists to provide a namespace in which to place all of these views,
	and perhaps to traverse further on.
	"""

	def __init__(self, context, request):
		self.context = context
		self.request = request

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

@view_config(name="get_courses", **_view_defaults)
class GetCoursesView(pyramid_views.GetCoursesView):
	""" Return all course items """

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

@view_config(name="enroll_course", **_post_view_defaults)
class EnrollCourseView(pyramid_views.EnrollCourseView):
	""" enroll a course """

@view_config(name="unenroll_course", **_post_view_defaults)
class UnenrollCourseView(pyramid_views.UnenrollCourseView):
	""" unenroll a course """

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
				pyramid_views._sync_purchase(purchase)
		return purchase

del _view_defaults
del _post_view_defaults
