#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.appserver import MessageFactory as _

import isodate
import datetime

from zope import component
from zope.traversing.interfaces import IPathAdapter

from pyramid.threadlocal import get_current_request

from nti.appserver.interfaces import IApplicationSettings
from nti.appserver._email_utils import queue_simple_html_text_email

from nti.dataserver.users.interfaces import IUserProfile

from nti.externalization.externalization import to_external_object

from nti.store.invitations import get_invitation_code
from nti.store.interfaces import IPurchaseAttemptSuccessful

def _send_purchase_confirmation(event, email):

	# Can only do this in the context of a user actually
	# doing something; we need the request for locale information
	# as well as URL information.
	request = getattr(event, 'request', get_current_request())
	if not request or not email:
		return

	purchase = event.object
	user = purchase.creator
	profile = IUserProfile(user)

	user_ext = to_external_object(user)
	informal_username = user_ext.get('NonI18NFirstName', profile.realname) or user.username

	# Provide functions the templates can call to format currency values
	currency = component.getAdapter( event, IPathAdapter, name='currency' )

	discount = -(event.purchase.Pricing.TotalNonDiscountedPrice -
				 event.purchase.Pricing.TotalPurchasePrice)
	formatted_discount = component.getAdapter(purchase.Pricing, IPathAdapter,
											  name='currency')
	formatted_discount = formatted_discount.format_currency_object(discount)

	charge_name = getattr(event.charge, 'Name', None)

	args = {'profile': profile,
			'context': event,
			'user': user,
			'format_currency': currency.format_currency_object,
			'format_currency_attribute': currency.format_currency_attribute,
			'discount': discount,
			'formatted_discount': formatted_discount,
			'transaction_id': get_invitation_code(purchase),  # We use invitation code as trx id
			'informal_username': informal_username,
			'billed_to': charge_name or profile.realname or informal_username,
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

@component.adapter(IPurchaseAttemptSuccessful)
def _purchase_attempt_successful(event):
	# If we reach this point, it means the charge has already gone through
	# don't fail the transaction if there is an error sending
	# the purchase confirmation email
	profile = IUserProfile(event.object.creator)
	email = getattr(profile, 'email')
	safe_send_purchase_confirmation(event, email)

@component.adapter(IPurchaseAttemptSuccessful)
def _purchase_attempt_successful_additional(event):
	# FIXME: This should probably NOT be the same template as goes to the user.
	settings = component.queryUtility(IApplicationSettings) or {}
	email_line = settings.get('purchase_additional_confirmation_addresses', '')
	for email in email_line.split():
		safe_send_purchase_confirmation(event, email)

