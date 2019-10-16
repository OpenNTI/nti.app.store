#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import datetime

import isodate

from zope import component
from zope import interface

from zope.traversing.interfaces import IPathAdapter

from pyramid.threadlocal import get_current_request

from nti.app.store import MessageFactory as _

from nti.appserver.policies.interfaces import ISitePolicyUserEventListener

from nti.dataserver.interfaces import IUser

from nti.externalization.externalization import to_external_object

from nti.mailer.interfaces import ITemplatedMailer

from nti.site.site import getSite

from nti.store.interfaces import IStorePurchaseMetadataProvider

from nti.store.store import get_transaction_code

DEFAULT_EMAIL_SUBJECT = _(u"Purchase Confirmation")
DEFAULT_PURCHASE_TEMPLATE = 'purchase_confirmation_email'

logger = __import__('logging').getLogger(__name__)


def queue_simple_html_text_email(*args, **kwargs):
    mailer = component.getUtility(ITemplatedMailer)
    result = mailer.queue_simple_html_text_email(*args, _level=6, **kwargs)
    return result


def send_purchase_confirmation(event,
                               email,
                               subject=DEFAULT_EMAIL_SUBJECT,
                               template=DEFAULT_PURCHASE_TEMPLATE,
                               package=None,
                               add_args=None):
    # Can only do this in the context of a user actually
    # doing something; we need the request for locale information
    # as well as URL information.
    request = getattr(event, 'request', get_current_request())
    if not request or not email:
        return
    purchase = event.object
    user = purchase.creator
    profile = purchase.Profile
    if IUser.providedBy(user):
        user_ext = to_external_object(user)
        informal_username = user_ext.get('NonI18NFirstName', profile.realname) \
                         or user.username
    else:
        informal_username = profile.realname or str(user)

    # Provide functions the templates can call to format currency values
    currency = component.getAdapter(event, IPathAdapter, name='currency')

    discount = -(purchase.Pricing.TotalNonDiscountedPrice -
                 purchase.Pricing.TotalPurchasePrice)

    formatted_discount = component.getAdapter(purchase.Pricing,
                                              IPathAdapter,
                                              name='currency')
    formatted_discount = formatted_discount.format_currency_object(discount,
                                                                   request=request)

    charge_name = getattr(event.charge, 'Name', None)

    policy = component.queryUtility(ISitePolicyUserEventListener)
    support_email = getattr(policy, 'SUPPORT_EMAIL', '')
    site_alias = getattr(policy, 'COM_ALIAS', '')
    refund_blurb = getattr(policy, 'REFUND_BLURB', u'All Sales Are Final')

    args = {'profile': profile,
            'context': event,
            'refund_blurb': refund_blurb,
            'user': user,
            'site_alias': site_alias,
            'support_email': support_email,
            'format_currency': currency.format_currency_object,
            'format_currency_attribute': currency.format_currency_attribute,
            'discount': discount,
            'formatted_discount': formatted_discount,
            'transaction_id': get_transaction_code(purchase),
            'informal_username': informal_username,
            'billed_to': charge_name or profile.realname or informal_username,
            'today': isodate.date_isoformat(datetime.datetime.now())}

    if add_args is not None:
        args.update(add_args)

    mailer = queue_simple_html_text_email
    mailer(template,
           subject=subject,
           recipients=[email],
           template_args=args,
           request=request,
           package=package,
           text_template_extension='.mak')


def safe_send_purchase_confirmation(event,
                                    email,
                                    subject=DEFAULT_EMAIL_SUBJECT,
                                    template=DEFAULT_PURCHASE_TEMPLATE,
                                    package=None,
                                    add_args=None):
    try:
        send_purchase_confirmation(event,
                                   email=email,
                                   subject=subject,
                                   template=template,
                                   package=package,
                                   add_args=add_args)
    except Exception:
        logger.exception("Error while sending purchase confirmation email to %s",
                         email)


def store_purchase_attempt_successful(event,
                                      subject=DEFAULT_EMAIL_SUBJECT,
                                      template=DEFAULT_PURCHASE_TEMPLATE,
                                      package=None,
                                      add_args=None):
    # If we reach this point, it means the charge has already gone through
    # don't fail the transaction if there is an error sending
    # the purchase confirmation email
    purchase = event.object
    email = purchase.Profile.email
    if email:
        safe_send_purchase_confirmation(event,
                                        email=email,
                                        subject=subject,
                                        template=template,
                                        package=package,
                                        add_args=add_args)
    else:
        logger.warn("Not sending purchase email because no user email was found")


@interface.implementer(IStorePurchaseMetadataProvider)
class SitePurchaseMetadataProvider(object):
    """
    Augment the purchase metadata with site information.
    """

    def update_metadata(self, data):
        data = data if data else {}
        data['Site'] = getattr(getSite(), '__name__', None)
        policy = component.getUtility(ISitePolicyUserEventListener)
        site_display = getattr(policy, 'BRAND', '')
        site_alias = getattr(policy, 'COM_ALIAS', '')
        # We are inhereting the NT brand, try to use alias.
        if site_display == 'NextThought' and site_alias:
            site_display = site_alias
        data['SiteName'] = site_display
        return data
