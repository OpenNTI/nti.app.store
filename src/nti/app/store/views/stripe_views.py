#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import json
import urllib
import urllib2

from uuid import uuid4

import requests

from requests.structures import CaseInsensitiveDict

import sys

from functools import partial

import transaction

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from six.moves import urllib_parse

from zope import component

from zope.cachedescriptors.property import Lazy

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.store import MessageFactory as _
from nti.app.store import STRIPE_CONNECT_AUTH
from nti.app.store import STRIPE_CONNECT_REDIRECT
from nti.app.store import DEFAULT_STRIPE_KEY_ALIAS

from nti.app.store.license_utils import can_integrate

from nti.app.store.utils import to_boolean
from nti.app.store.utils import is_valid_pve_int
from nti.app.store.utils import is_valid_boolean
from nti.app.store.utils import AbstractPostView

from nti.app.store.views import get_current_site
from nti.app.store.views import StorePathAdapter
from nti.app.store.views import StripePathAdapter

from nti.app.store.views.view_mixin import PriceOrderViewMixin
from nti.app.store.views.view_mixin import BasePaymentViewMixin
from nti.app.store.views.view_mixin import BaseProcessorViewMixin
from nti.app.store.views.view_mixin import GiftPreflightViewMixin
from nti.app.store.views.view_mixin import RefundPaymentViewMixin
from nti.app.store.views.view_mixin import GetProcesorConnectKeyViewMixin
from nti.app.store.views.view_mixin import GeneratePurchaseInvoiceViewMixin

from nti.app.store.views.view_mixin import price_order

from nti.base._compat import text_

from nti.common.interfaces import IOAuthKeys
from nti.common.interfaces import IOAuthService

from nti.common.string import is_true

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store import PricingException
from nti.store import InvalidPurchasable

from nti.store.interfaces import IPricingError
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import IPurchasableChoiceBundle

from nti.store.payments.stripe import authorization as sauth
from nti.store.payments.stripe import STRIPE
from nti.store.payments.stripe import NoSuchStripeCoupon
from nti.store.payments.stripe import InvalidStripeCoupon

from nti.store.payments.stripe.interfaces import IStripeConnectConfig
from nti.store.payments.stripe.interfaces import IStripeConnectKey
from nti.store.payments.stripe.interfaces import IStripePurchaseOrder
from nti.store.payments.stripe.interfaces import IStripeConnectKeyContainer
from nti.store.payments.stripe.interfaces import IStripeAccountInfo

from nti.store.payments.stripe.model import PersistentStripeConnectKey
from nti.store.payments.stripe.model import StripeToken

from nti.store.payments.stripe.storage import get_stripe_key_container

from nti.store.payments.stripe.stripe_purchase import create_stripe_priceable
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_item
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_order

from nti.store.payments.stripe.utils import replace_items_coupon

from nti.store.store import get_gift_pending_purchases
from nti.store.store import create_gift_purchase_attempt
from nti.store.store import register_gift_purchase_attempt

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import normal_resource_path

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED
_REQUEST_TIMEOUT = 1.0

logger = __import__('logging').getLogger(__name__)


class BaseStripeViewMixin(BaseProcessorViewMixin):
    processor = STRIPE
    key_interface = IStripeConnectKey


@view_config(name="GetStripeConnectKey")
@view_config(name="get_connect_key")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='GET')
class GetStripeConnectKeyView(AbstractAuthenticatedView,
                              GetProcesorConnectKeyViewMixin,
                              BaseStripeViewMixin):
    pass


@view_config(name="GetConnectKey")
@view_config(name="get_connect_key")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StripePathAdapter,
               request_method='GET')
class GetConnectKeyView(GetStripeConnectKeyView):
    pass


# pricing no-auth/permission views


def _call_pricing_func(func):
    try:
        result = func()
    except NoSuchStripeCoupon:
        result = IPricingError(_(u"Invalid coupon."))
    except InvalidStripeCoupon:
        result = IPricingError(_(u"Invalid coupon."))
    except InvalidPurchasable:
        result = IPricingError(_(u"Invalid purchasable."))
    except PricingException as e:
        result = IPricingError(e)
    except Exception:
        raise
    return result


@view_config(name="PriceStripeOrder")
@view_config(name="price_stripe_order")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class PriceStripeOrderView(AbstractAuthenticatedView,
                           BaseStripeViewMixin,
                           PriceOrderViewMixin):

    content_predicate = IStripePurchaseOrder.providedBy

    def _do_pricing(self, order):
        result = _call_pricing_func(partial(price_order, order, self.processor))
        status = 422 if IPricingError.providedBy(result) else 200
        self.request.response.status_int = status
        return result

    def _do_call(self):
        order = self.readCreateUpdateContentObject()
        assert IStripePurchaseOrder.providedBy(order)
        if order.Coupon:  # replace item coupons
            replace_items_coupon(order, None)
        return self._do_pricing(order)


@view_config(name="PriceOrder")
@view_config(name="price_order")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StripePathAdapter,
               request_method='POST')
class PriceOrderView(PriceStripeOrderView):
    pass


def perform_pricing(purchasable_id, quantity=None, coupon=None):
    pricer = component.getUtility(IPurchasablePricer, name=STRIPE)
    priceable = create_stripe_priceable(ntiid=purchasable_id,
                                        quantity=quantity,
                                        coupon=coupon)
    result = pricer.price(priceable)
    return result


@view_config(name="PricePurchasableWithStripeCoupon")
@view_config(name="price_purchasable_with_stripe_coupon")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class PricePurchasableWithStripeCouponView(AbstractPostView,
                                           BaseStripeViewMixin):

    def price_purchasable(self, values=None):
        values = values or self.readInput()
        coupon = values.get('code') \
              or values.get('coupon') \
              or values.get('couponCode')
        purchasable_id = values.get('ntiid') \
                      or values.get('purchasable') \
                      or values.get('purchasableId') \
                      or values.get('purchasable_Id')

        # check quantity
        quantity = values.get('quantity', 1)
        if not is_valid_pve_int(quantity):
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid quantity."),
                            'field': 'quantity'
                        },
                        None)
        quantity = int(quantity)

        pricing_func = partial(perform_pricing,
                               coupon=coupon,
                               quantity=quantity,
                               purchasable_id=purchasable_id)
        result = _call_pricing_func(pricing_func)
        status = 422 if IPricingError.providedBy(result) else 200
        self.request.response.status_int = status
        return result

    def __call__(self):
        result = self.price_purchasable()
        return result


@view_config(name="PricePurchasable")
@view_config(name="price_purchasable")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StripePathAdapter,
               request_method='POST')
class PricePurchasableView(PricePurchasableWithStripeCouponView):
    pass


# token views


@view_config(name="CreateStripeToken")
@view_config(name="create_stripe_token")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='POST')
class CreateStripeTokenView(AbstractPostView, BaseStripeViewMixin):

    def __call__(self):
        values = self.readInput()
        __traceback_info__ = values, self.request.params

        stripe_key = self.get_connect_key(values)
        manager = component.getUtility(IPaymentProcessor,
                                       name=self.processor)

        params = {'api_key': stripe_key.PrivateKey}
        customer_id = values.get('customer') \
                   or values.get('customerId') \
                   or values.get('customer_id')
        if not customer_id:
            required = (('cvc', 'cvv', 'card_cvv'),
                        ('number', 'cc', 'card_number'),
                        ('card_expiry', 'card_expiry', 'expiry'))

            for k, p, a in required:
                value = values.get(k) or values.get(p) or values.get(a)
                if not value:
                    raise_error(self.request,
                                hexc.HTTPUnprocessableEntity,
                                {
                                    'message': _(u"Invalid value."),
                                    'field': p
                                },
                                None)
                params[k] = text_(value)
            expiry = params.pop('card_expiry', u'')
            index = 2 if len(expiry) >= 4 else 1
            params['exp_year'] = expiry[index:]
            params['exp_month'] = expiry[0:index]
        else:
            params['customer_id'] = customer_id

        # optional
        optional = (('address_line1', 'street', 'address'),
                    ('address_line2', 'street2', 'street_2'),
                    ('address_city', 'address_city', 'city'),
                    ('address_state', 'address_state', 'state'),
                    ('address_zip', 'zip_code', 'zip'),
                    ('address_country', 'address_country', 'country'))
        for k, p, a in optional:
            value = values.get(k) or values.get(p) or values.get(a)
            if value:
                params[k] = text_(value)

        token = manager.create_token(**params)
        result = StripeToken(Value=token.id,
                             Type=token.card.brand,
                             CardID=token.card.id)
        return result


@view_config(name="CreateToken")
@view_config(name="create_token")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StripePathAdapter,
               request_method='POST')
class CreateTokenView(CreateStripeTokenView):
    pass


# purchase views


def process_purchase(manager, purchase_id, username, token, expected_amount,
                     stripe_key, request, site_name=None):
    logger.info("Processing purchase %s", purchase_id)
    manager.process_purchase(token=token,
                             request=request,
                             username=username,
                             site_name=site_name,
                             purchase_id=purchase_id,
                             api_key=stripe_key.PrivateKey,
                             expected_amount=expected_amount,)


def addAfterCommitHook(manager, purchase_id, username, token, expected_amount,
                       stripe_key, request, site_name=None):

    processor = partial(process_purchase,
                        token=token,
                        request=request,
                        manager=manager,
                        username=username,
                        site_name=site_name,
                        stripe_key=stripe_key,
                        purchase_id=purchase_id,
                        expected_amount=expected_amount)

    def hook(s): return s and request.nti_gevent_spawn(processor)
    transaction.get().addAfterCommitHook(hook)


def validate_coupon(request, coupon, api_key):
    if coupon:
        manager = component.getUtility(IPaymentProcessor, name=STRIPE)
        try:
            if not manager.validate_coupon(coupon, api_key):
                raise_error(request,
                            hexc.HTTPUnprocessableEntity,
                            {
                                'message': _(u"Invalid coupon."),
                                'field': u'coupon'
                            },
                            None)
        except StandardError as e:
            exc_info = sys.exc_info()
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid coupon."),
                            'field': 'coupon',
                            'code': e.__class__.__name__
                        },
                        exc_info[2])
    return coupon


def validate_stripe_key(request, purchasables=()):
    result = None
    for purchasable in purchasables or ():
        provider = purchasable.Provider
        stripe_key = component.queryUtility(IStripeConnectKey, provider)
        if stripe_key is None:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid purchasable provider."),
                            'field': 'purchasables',
                            'value': provider
                        },
                        None)
        if result is None:
            result = stripe_key
        elif result != stripe_key:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Cannot mix purchasable providers."),
                            'field': 'purchasables'
                        },
                        None)
    if result is None:
        raise_error(request,
                    hexc.HTTPUnprocessableEntity,
                    {
                        'message': _(u"Could not find a purchasable provider."),
                        'field': 'purchasables'
                    },
                    None)
    return result


class BasePaymentWithStripeView(BasePaymentViewMixin):

    processor = STRIPE

    def getPaymentRecord(self, request, values=None):
        values = values or self.readInput()
        result = BasePaymentViewMixin.getPaymentRecord(self, request, values)
        # validate stripe key
        purchasables = self.resolvePurchasables(result['Purchasables'])
        stripe_key = validate_stripe_key(request, purchasables)
        result['StripeKey'] = stripe_key
        # validate coupon
        coupon = values.get('coupon', None)
        coupon = validate_coupon(request, coupon, stripe_key.PrivateKey)
        result['Coupon'] = coupon
        return result

    def createPurchaseOrder(self, record):
        purchasables = record['Purchasables']
        items = [create_stripe_purchase_item(p) for p in purchasables]
        result = create_stripe_purchase_order(tuple(items),
                                              quantity=record['Quantity'],
                                              coupon=record['coupon'])
        return result

    def processPurchase(self, purchase_attempt, record):
        purchase_id = self.registerPurchaseAttempt(purchase_attempt, record)
        logger.info("Purchase attempt (%s) created", purchase_id)

        token = record['Token']
        stripe_key = record['StripeKey']
        expected_amount = record['ExpectedAmount']

        request = self.request
        username = self.username
        site_name = get_current_site()
        manager = component.getUtility(IPaymentProcessor, name=self.processor)

        # process purchase after commit
        addAfterCommitHook(token=token,
                           request=request,
                           manager=manager,
                           username=username,
                           site_name=site_name,
                           stripe_key=stripe_key,
                           purchase_id=purchase_id,
                           expected_amount=expected_amount)

        # return
        result = LocatedExternalDict({
            ITEMS: [purchase_attempt],
            LAST_MODIFIED: purchase_attempt.lastModified
        })
        return result


@view_config(name="PostStripePayment")
@view_config(name="post_stripe_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='POST')
class ProcessPaymentWithStripeView(AbstractPostView,
                                   BasePaymentWithStripeView):

    def validatePurchasable(self, request, purchasable_id):
        purchasable = super(ProcessPaymentWithStripeView, self).validatePurchasable(request, purchasable_id)
        if IPurchasableChoiceBundle.providedBy(purchasable):
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Cannot purchase a bundle item."),
                            'field': 'purchasables',
                            'value': purchasable_id
                        },
                        None)
        return purchasable


@view_config(name="PostPayment")
@view_config(name="post_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StripePathAdapter,
               request_method='POST')
class ProcessPaymentView(ProcessPaymentWithStripeView):
    pass


@view_config(name="GiftStripePaymentPreflight")
@view_config(name="gift_stripe_payment_preflight")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class GiftWithStripePreflightView(AbstractPostView,
                                  GiftPreflightViewMixin):

    processor = STRIPE

    def validatePurchasables(self, request, values, purchasables=()):
        result = super(GiftWithStripePreflightView, self).validatePurchasables(request, values, purchasables)
        count = sum(1 for x in result if IPurchasableChoiceBundle.providedBy(x))
        if count and len(result) > 1:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Can only purchase one bundle item at a time."),
                            'field': 'purchasables'
                        },
                        None)
        return result

    def getPaymentRecord(self, request, values):
        record = super(GiftWithStripePreflightView, self).getPaymentRecord(request, values)
        # validate stripe key
        purchasables = self.resolvePurchasables(record['Purchasables'])
        stripe_key = validate_stripe_key(request, purchasables)
        record['StripeKey'] = stripe_key
        # validate coupon
        coupon = values.get('coupon', None)
        coupon = validate_coupon(request, coupon, stripe_key.PrivateKey)
        record['Coupon'] = coupon
        return record

    @property
    def username(self):
        return None

    def __call__(self):
        values = self.readInput()
        request = self.request
        record = self.getPaymentRecord(request, values)
        return record


@view_config(name="GiftPaymentPreflight")
@view_config(name="gift_payment_preflight")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StripePathAdapter,
               request_method='POST')
class GiftPreflightView(GiftWithStripePreflightView):
    pass


@view_config(name="GiftStripePayment")
@view_config(name="gift_stripe_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class GiftWithStripeView(GiftWithStripePreflightView,
                         BasePaymentWithStripeView):

    def createPurchaseAttempt(self, record):
        order = self.createPurchaseOrder(record)
        result = create_gift_purchase_attempt(order=order,
                                              processor=self.processor,
                                              sender=record['Sender'],
                                              creator=record['Creator'],
                                              message=record['Message'],
                                              context=record['Context'],
                                              receiver=record['Receiver'],
                                              receiver_name=record['ReceiverName'],
                                              delivery_date=record['DeliveryDate'])
        return result

    def registerPurchaseAttempt(self, purchase, record):
        result = register_gift_purchase_attempt(record['Creator'], purchase)
        return result

    @property
    def username(self):
        return None

    def __call__(self):
        values = self.readInput()
        record = self.getPaymentRecord(self.request, values)
        purchase_attempt = self.createPurchaseAttempt(record)

        # check for any pending gift purchase
        creator = record['Creator']
        purchases = get_gift_pending_purchases(creator)
        if purchases:
            lastModified = max(x.lastModified for x in purchases) or 0
            logger.warn("There are pending purchase(s) for item(s) %s",
                        list(purchase_attempt.Items))
            return LocatedExternalDict({
                ITEMS: purchases,
                LAST_MODIFIED: lastModified
            })
        result = self.processPurchase(purchase_attempt, record)
        return result


@view_config(name="GiftPayment")
@view_config(name="gift_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StripePathAdapter,
               request_method='POST')
class GiftPaymentView(GiftWithStripeView):
    pass


# invoice


@view_config(name="GeneratePurchaseInvoiceWithStripe")
@view_config(name="generate_purchase_invoice_with_stripe")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='POST')
class GeneratePurchaseInvoiceWitStripeView(AbstractPostView,
                                           BaseStripeViewMixin,
                                           GeneratePurchaseInvoiceViewMixin):
    pass


@view_config(name="GeneratePurchaseInvoice")
@view_config(name="generate_purchase_invoice")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StripePathAdapter,
               request_method='POST')
class GeneratePurchaseInvoiceView(GeneratePurchaseInvoiceWitStripeView):
    pass


# refund


def refund_purchase(purchase, amount, refund_application_fee=None, request=None):
    manager = component.getUtility(IPaymentProcessor, name=STRIPE)
    return manager.refund_purchase(purchase,
                                   amount=amount,
                                   request=request,
                                   refund_application_fee=refund_application_fee)


@view_config(name="RefundPaymentWithStripe")
@view_config(name="refund_payment_with_stripe")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=StorePathAdapter,
               request_method='POST')
class RefundPaymentWithStripeView(AbstractPostView,
                                  BaseStripeViewMixin,
                                  RefundPaymentViewMixin):

    def processInput(self, values=None):
        values = self.readInput()
        purchase, amount = super(RefundPaymentWithStripeView, self).processInput(values)
        # validate refund fee
        refund_application_fee = values.get('refundApplicationFee') \
                              or values.get('refund_application_fee')
        if refund_application_fee is not None:
            if not is_valid_boolean(refund_application_fee):
                raise_error(self.request,
                            hexc.HTTPUnprocessableEntity,
                            {
                                'message': _(u"Please provide a valid application fee."),
                                'field': 'refundApplicationFee'
                            },
                            None)
            refund_application_fee = to_boolean(refund_application_fee)
        # return
        return purchase, amount, refund_application_fee

    def __call__(self):
        request = self.request
        purchase, amount, refund_application_fee = self.processInput()
        try:
            refund_purchase(purchase,
                            amount=amount,
                            refund_application_fee=refund_application_fee,
                            request=request)
        except Exception as e:
            logger.exception("Error while refunding transaction")
            exc_info = sys.exc_info()
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Error while refunding transaction."),
                            'code': e.__class__.__name__
                        },
                        exc_info[2])

        result = LocatedExternalDict({
            ITEMS: [purchase],
            LAST_MODIFIED: purchase.lastModified
        })
        return result


@view_config(name="RefundPayment")
@view_config(name="refund_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=StripePathAdapter,
               request_method='POST')
class RefundPaymentView(RefundPaymentWithStripeView):
    pass


def url_with_params(url, params):
    url_parts = list(urllib_parse.urlparse(url))
    query = dict(urllib_parse.parse_qsl(url_parts[4]))
    query.update(params)
    url_parts[4] = urllib_parse.urlencode(query)
    return urllib_parse.urlunparse(url_parts)


class StripeConnectViewMixin(object):

    @Lazy
    def stripe_conf(self):
        return component.getUtility(IStripeConnectConfig)

    @Lazy
    def oauth_keys(self):
        return component.getUtility(IOAuthKeys, name="stripe")

    @Lazy
    def nti_client_secret(self):
        return self.oauth_keys.ClientSecret

    @Lazy
    def nti_client_id(self):
        return self.oauth_keys.ClientId

    def _relative_url(self, base_url, path):
        path_parts = urllib_parse.urlparse(path)
        base_parts = urllib_parse.urlparse(base_url)

        return urllib_parse.urlunparse(base_parts[:2] + path_parts[2:])

    @Lazy
    def success_endpoint(self):
        return self._relative_url(self.request.application_url,
                                  self.request.session.get("stripe.success"))

    @Lazy
    def failure_endpoint(self):
        return self._relative_url(self.request.application_url,
                                  self.request.session.get("stripe.failure"))

    def redirect_with_params(self, loc, params=None):
        url = url_with_params(loc, params or {})
        return hexc.HTTPSeeOther(url)

    def error_response(self, error='Unknown', desc='An unknown error occurred'):
        return self.redirect_with_params(self.failure_endpoint,
                                         {'error': error, 'error_description': desc})


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             request_method='GET',
             context=IStripeConnectKeyContainer,
             permission=sauth.ACT_LINK_STRIPE,
             name=STRIPE_CONNECT_AUTH)
class StripeConnectAuthorization(StripeConnectViewMixin, AbstractAuthenticatedView):
    """
    A redirect to the Stripe OAuth endpoint that will start the
    authorization process to link a customer's Stripe account with ours.
    """

    @Lazy
    def _stripe_connect_key(self):
        return component.queryUtility(IStripeConnectKey, name=DEFAULT_STRIPE_KEY_ALIAS)

    def _stripe_redirect_uri(self):
        path = normal_resource_path(get_stripe_key_container())

        path = urllib_parse.urljoin(self.request.application_url,
                                    path)
        return urllib_parse.urljoin(path + '/' if not path.endswith('/') else path,
                                    "@@" + STRIPE_CONNECT_REDIRECT)

    def __call__(self):
        for key in ('success', 'failure'):
            value = self.request.params.get(key)

            if not value:
                raise hexc.HTTPBadRequest("No %s endpoint specified." % (key,))

            self.request.session['stripe.' + key] = value

        if self._stripe_connect_key is not None:
            return self.error_response('Already Linked',
                                       "Another account has already been linked for this site.")

        if not can_integrate():
            return self.error_response(self.dest_endpoint,
                                       'Cannot link account',
                                       "This site is not permitted to link stripe accounts.")

        # redirect
        auth_svc = component.getUtility(IOAuthService, name="stripe")
        target = auth_svc.authorization_request_uri(
            client_id=self.nti_client_id,
            response_type="code",
            scope="read_write",
            redirect_uri=self._stripe_redirect_uri(),
            stripe_landing="login"
        )

        # save state for validation, which could be modified by auth_svc
        self.request.session['stripe.state'] = auth_svc.params['state']

        return hexc.HTTPSeeOther(location=target)


@view_config(name=STRIPE_CONNECT_REDIRECT)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='GET',
               context=IStripeConnectKeyContainer,
               permission=sauth.ACT_LINK_STRIPE)
class ConnectStripeAccount(StripeConnectViewMixin, AbstractAuthenticatedView):
    """
    This is the redirection endpoint
    (https://tools.ietf.org/html/rfc6749#section-3.1.2) of the OAuth flow
    used when connecting a Stripe account for one of our sites
    (https://stripe.com/docs/connect/standard-accounts).  It, thus, expects
    a `code` parameter containing the authorization code to use in the
    token request, or an `error` and `error_description` describing any
    issue with the authorization.
    """

    def _text(self, s, encoding='utf-8', errors='strict'):
        return s.decode(encoding=encoding, errors=errors) \
            if isinstance(s, bytes) else s

    def success_response(self):
        return self.redirect_with_params(self.success_endpoint)

    def retrieve_keys(self, code):
        try:
            data = urllib.urlencode({'client_secret': self.nti_client_secret})
            url = url_with_params(self.stripe_conf.TokenEndpoint,
                                  {
                                      'grant_type': 'authorization_code',
                                      'code': code
                                  })
            response = urllib2.urlopen(url, data)

            response_code = response.getcode()

            if response_code < 200 or response_code >= 300:
                return self.error_response()

            return self.persist_data(response)
        except Exception:
            error_uid = str(uuid4())
            logger.exception("Exception making token request (%s): ", error_uid)
            return self.error_response('Server Error',
                                       "Error Reference: %s" % (error_uid,))

    def _add_key(self, connect_key):
        self.context.add_key(connect_key)

    def persist_data(self, response):
        try:
            result = json.load(response)
            connect_key = PersistentStripeConnectKey(
                Alias=DEFAULT_STRIPE_KEY_ALIAS,
                StripeUserID=self._text(result['stripe_user_id']),
                LiveMode=bool(result['livemode']),
                PrivateKey=self._text(result['access_token']),
                RefreshToken=self._text(result['refresh_token']),
                PublicKey=self._text(result['stripe_publishable_key']),
                TokenType=self._text(result['token_type'])
            )
            connect_key.creator = self.remoteUser
            try:
                self._add_key(connect_key)
            except KeyError:
                return self.error_response('Already Linked',
                                           "Another account has already been linked for this site.")

            response = self.success_response()

            self.request.environ['nti.request_had_transaction_side_effects'] = 'True'
            return response
        except Exception:
            error_uid = str(uuid4())
            logger.exception("Exception persisting data (%s): ", error_uid)
            return self.error_response('Server Error',
                                       "Error Reference: %s" % (error_uid,))

    def __call__(self):
        params = CaseInsensitiveDict( self.request.params)

        if "error" in params or "error_description" in params:
            return self.error_response(self._text(params.get("error")),
                                       self._text(params.get("error_description")))

        if "code" not in params:
            return self.error_response(_(u"Invalid Request"),
                                       _(u"Missing parameter: code"))
        code = self._text(params.get('code'))

        if "state" not in params:
            return self.error_response(_(u"Invalid Request"),
                                       _(u"Missing parameter: state"))
        state = self._text(params.get('state'))

        session_state = self.request.session['stripe.state']
        if not state or state != session_state:
            error_uid = str(uuid4())
            logger.error("State returned (%s) doesn't match state sent (%s): %s",
                         state,
                         session_state,
                         error_uid)
            return self.error_response('Server Error',
                                       "Error Reference: %s" % (error_uid,))

        return self.retrieve_keys(code)


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             request_method='DELETE',
             context=IStripeConnectKey,
             permission=sauth.ACT_LINK_STRIPE)
class DisconnectStripeAccount(StripeConnectViewMixin, AbstractAuthenticatedView):

    @Lazy
    def _deauth_uri(self):
        return self.stripe_conf.DeauthorizeEndpoint

    def _deauth_stripe(self, user_key):
        data = {
            'client_id': self.nti_client_id,
            'stripe_user_id': user_key.StripeUserID
        }
        deauth = requests.post(self._deauth_uri,
                               data=data,
                               timeout=_REQUEST_TIMEOUT,
                               auth=(self.nti_client_secret,''))

        try:
            deauth.raise_for_status()
        except requests.RequestException as req_ex:
            logger.exception("Unable to deauthorize platform access for user: %s",
                             user_key.StripeUserID)
            raise hexc.HTTPServerError(str(req_ex))

    def __call__(self):
        container = find_interface(self.context, IStripeConnectKeyContainer)
        if not is_true(self.request.params.get('skip_deauth')):
            self._deauth_stripe(self.context)
        container.remove_key(DEFAULT_STRIPE_KEY_ALIAS)
        return hexc.HTTPNoContent()


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             context=IStripeConnectKeyContainer,
             permission=sauth.ACT_VIEW_STRIPE_ACCOUNT,
             name="account_info")
class ViewAccount(AbstractAuthenticatedView,
                  GetProcesorConnectKeyViewMixin,
                  BaseStripeViewMixin):

    def __call__(self):
        connect_key = super(ViewAccount, self).__call__()
        return IStripeAccountInfo(connect_key)
