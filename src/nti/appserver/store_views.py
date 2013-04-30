#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views and other objects relating to NTI store

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import isodate
import datetime

from zope import component
from zope import interface
from zope.location.interfaces import IContained
from zope.traversing.interfaces import IPathAdapter
from zope.publisher.interfaces.browser import IBrowserRequest

from pyramid.view import view_config
from pyramid.threadlocal import get_current_request

from nti.appserver import MessageFactory as _
from nti.appserver._email_utils import queue_simple_html_text_email

from nti.dataserver import authorization as nauth
from nti.dataserver.users import interfaces as user_interfaces

from nti.externalization.externalization import to_external_object

from nti.store import invitations
from nti.store import pyramid_views
from nti.store import interfaces as store_interfaces

def _send_purchase_confirmation_email(event):
	# Can only do this in the context of a user actually
	# doing something; we need the request for locale information
	# as well as URL information.
	request = getattr(event, 'request', get_current_request())
	if not request:
		return

	purchase = event.object
	user = purchase.creator
	profile = user_interfaces.IUserProfile(user)
	email = getattr(profile, 'email')
	if not email:
		return

	user_ext = to_external_object(user)
	informal_username = user_ext.get('NonI18NFirstName', profile.realname) or user.username

	# Provide functions the templates can call to format currency values
	# (TODO: Could this be an tales:expresiontype for the PT template?
	# Probably not, looks like z3c.pt/Chameleon doesn't support extensible expressions;
	# but it does support path adapters, so we could do something like:
	#   context/charge/fc:Amount
	# where fc is a named IPathAdapter that supports traversing the charge object's Amount
	# attribute as a formatted string)
	locale = IBrowserRequest(request).locale
	currency_format = locale.numbers.getFormatter('currency')
	def format_currency(decimal, currency=None):
		if currency is None:
			try:
				currency = locale.getDefaultCurrency()
			except AttributeError:
				currency = 'USD'
		currency = locale.numbers.currencies[currency]
		formatted = currency_format.format(decimal)
		# Replace the currency symbol placeholder with its real value.
		# see  http://www.mail-archive.com/zope3-users@zope.org/msg04721.html
		formatted = formatted.replace('\xa4', currency.symbol)
		return formatted

	def format_currency_attribute(obj, attrname):
		return format_currency(getattr(obj, attrname), getattr(obj, 'Currency'))

	args = {'profile': profile,
			'context': event,
			'user': user,
			'format_currency': format_currency,
			'format_currency_attribute': format_currency_attribute,
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

@component.adapter(store_interfaces.IPurchaseAttemptSuccessful)
def _purchase_attempt_successful(event):
	try:
		# If we reach this point, it means the charge has already gone through
		# don't fail the transaction if there is an error sending
		# the purchase confirmation email
		_send_purchase_confirmation_email(event)
	except Exception:
		logger.exception("Error while sending purchase confirmation email")

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

# object get views

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context='nti.store.interfaces.IPurchasable',
			 permission=nauth.ACT_READ,
			 request_method='GET')
class PurchasableGetView(pyramid_views.PurchasableGetView):
	pass

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context='nti.store.interfaces.IPurchaseAttempt',
			 permission=nauth.ACT_READ,
			 request_method='GET')
class PurchaseAttemptGetView(pyramid_views.PurchaseAttemptGetView):
	pass

# admin - views

_view_admin_defaults = _view_defaults.copy()
_view_admin_defaults['permission'] = nauth.ACT_MODERATE

@view_config(name="get_content_roles", **_view_admin_defaults)
class GetContentRolesView(pyramid_views.GetContentRolesView):
	""" return the a list /w the content roles """

@view_config(name="refund_purchase_attempt", **_admin_view_defaults)
class RefundPurchaseAttemptView(pyramid_views.RefundPurchaseAttemptView):
	""" delete a purchase attempt """

@view_config(name="delete_purchase_attempt", **_admin_view_defaults)
class DeletePurchaseAttemptView(pyramid_views.DeletePurchaseAttemptView):
	""" delete a purchase attempt """

@view_config(name="delete_purchase_history", **_admin_view_defaults)
class DeletePurchaseHistoryView(pyramid_views.DeletePurchaseHistoryView):
	""" delete a purchase history """

del _view_defaults
del _post_view_defaults
del _admin_view_defaults
del _view_admin_defaults
