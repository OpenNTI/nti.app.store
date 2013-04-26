#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views and other objects relating to NTI store

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)
from nti.appserver import MessageFactory as _

import isodate
import datetime

from zope import component
from zope import interface
from zope.traversing.interfaces import IPathAdapter
from zope.location.interfaces import IContained

from pyramid.view import view_config
from pyramid.threadlocal import get_current_request

from nti.appserver._email_utils import create_simple_html_text_email

from nti.dataserver import authorization as nauth
# from nti.externalization.oids import to_external_oid
from nti.externalization.externalization import to_external_object

from nti.store import interfaces as store_interfaces
from nti.dataserver.users import interfaces as user_interfaces

from nti.store import invitations
from nti.store import pyramid_views

class _IMailer(interface.Interface):
	"""
	Marker interface that lets us easily switch in and out
	which function we use for sending confirmation emails during testing.
	"""

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

	request = get_current_request()
	if not request:
		# Can only do this in the context of a user actually
		# doing something
		return

	purchase = event.object
	user = purchase.creator
	profile = user_interfaces.IUserProfile(user)
	email = getattr(profile, 'email')
	if not email:
		return

	transaction_id = invitations.get_invitation_code(purchase)
	user_ext = to_external_object(user)
	informal_username = user_ext.get('NonI18NFirstName', profile.realname) or user.username

	args = {'profile': profile,
			'context': event,
			'user': user,
			'transaction_id': transaction_id,  # We use invitation code as trx id
			'informal_username': informal_username,
			'billed_to': event.charge.Name or profile.realname or informal_username,
			'today': isodate.date_isoformat(datetime.datetime.now()) }
	# Notice we're only creating it, not queueing it, as we work through
	# the templates (except in test mode)

	mailer = component.queryUtility(_IMailer, default=create_simple_html_text_email)
	mailer('purchase_confirmation_email',
			subject=_("Purchase Confirmation"),
			recipients=[email],
			template_args=args,
			text_template_extension='.mak')





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

_view_admin_defaults = _view_defaults.copy()
_view_admin_defaults['permission'] = nauth.ACT_MODERATE

@view_config(name="get_content_roles", **_view_admin_defaults)
class GetContentRolesView(pyramid_views.GetContentRolesView):
	""" return the a list /w the content roles """

@view_config(name="delete_purchase_attempt", **_admin_view_defaults)
class DeletePurchaseAttemptView(pyramid_views.DeletePurchaseAttemptView):
	""" delete a purchase attempt """

@view_config(name="delete_purchase_history", **_admin_view_defaults)
class DeletePurchaseHistoryView(pyramid_views.DeletePurchaseHistoryView):
	""" delete a purchase history """

from .dataserver_pyramid_views import _GenericGetView as GenericGetView
@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context='nti.store.interfaces.IPurchasable',
			 permission=nauth.ACT_READ,
			 request_method='GET')
class PurchasableGetView(GenericGetView):
	pass


del _view_defaults
del _post_view_defaults
del _admin_view_defaults
del _view_admin_defaults
