#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import sys
from functools import partial

from zope import component

import transaction

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.store import MessageFactory as _

from nti.app.store.utils import to_boolean
from nti.app.store.utils import is_valid_pve_int
from nti.app.store.utils import is_valid_boolean
from nti.app.store.utils import AbstractPostView 

from nti.app.store.views import get_current_site
from nti.app.store.views import StorePathAdapter

from nti.app.store.views.view_mixin import PriceOrderViewMixin
from nti.app.store.views.view_mixin import BasePaymentViewMixin
from nti.app.store.views.view_mixin import BaseProcessorViewMixin
from nti.app.store.views.view_mixin import GiftPreflightViewMixin
from nti.app.store.views.view_mixin import RefundPaymentViewMixin
from nti.app.store.views.view_mixin import GetProcesorConnectKeyViewMixin
from nti.app.store.views.view_mixin import GeneratePurchaseInvoiceViewMixin

from nti.app.store.views.view_mixin import price_order

from nti.base._compat import text_

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store import PricingException
from nti.store import InvalidPurchasable

from nti.store.interfaces import IPricingError
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import IPurchasableChoiceBundle

from nti.store.payments.stripe import STRIPE
from nti.store.payments.stripe import NoSuchStripeCoupon
from nti.store.payments.stripe import InvalidStripeCoupon

from nti.store.payments.stripe.interfaces import IStripeConnectKey
from nti.store.payments.stripe.interfaces import IStripePurchaseOrder

from nti.store.payments.stripe.stripe_purchase import create_stripe_priceable
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_item
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_order

from nti.store.payments.stripe.utils import replace_items_coupon

from nti.store.store import get_gift_pending_purchases
from nti.store.store import create_gift_purchase_attempt
from nti.store.store import register_gift_purchase_attempt

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED


class BaseStripeViewMixin(BaseProcessorViewMixin):
    processor = STRIPE
    key_interface = IStripeConnectKey   


@view_config(name="GetStripeConnectKey")
@view_config(name="get_connect_key") # TODO: remove
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='GET')
class GetStripeConnectKeyView(AbstractAuthenticatedView,
                              GetProcesorConnectKeyViewMixin,
                              BaseStripeViewMixin):
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
        if order.Coupon: # replace item coupons
            replace_items_coupon(order, None)
        return self._do_pricing(order)


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
                            'field': u'quantity'
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
                   or values.get('customerID') \
                   or values.get('customer_id')
        if not customer_id:
            required = (('cvc', 'cvc', ''),
                        ('exp_year', 'expYear', 'exp_year'),
                        ('exp_month', 'expMonth', 'exp_month'),
                        ('number', 'CC', 'number'))

            for key, param, alias in required:
                value = values.get(param) or values.get(alias)
                if not value:
                    raise_error(self.request,
                                hexc.HTTPUnprocessableEntity,
                                {    
                                    'message': _(u"Invalid value."),
                                    'field': param
                                },
                                None)
                params[key] = text_(value)
        else:
            params['customer_id'] = customer_id

        # optional
        optional = (('address_line1', 'address_line1', 'address'),
                    ('address_line2', 'address_line2', ''),
                    ('address_city', 'address_city', 'city'),
                    ('address_state', 'address_state', 'state'),
                    ('address_zip', 'address_zip', 'zip'),
                    ('address_country', 'address_country', 'country'))
        for k, p, a in optional:
            value = values.get(p) or values.get(a)
            if value:
                params[k] = text_(value)

        token = manager.create_token(**params)
        result = LocatedExternalDict(Token=token.id)
        return result


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

    hook = lambda s: s and request.nti_gevent_spawn(processor)
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
                            'field': u'coupon',
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
                            'field': u'purchasables',
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
                            'field': u'purchasables'
                        },
                        None)
    if result is None:
        raise_error(request,
                    hexc.HTTPUnprocessableEntity,
                    {    
                        'message': _(u"Could not find a purchasable provider."),
                        'field': u'purchasables'
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
        site_name = get_current_site ()
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
                            'field': u'purchasables',
                            'value': purchasable_id
                        },
                        None)
        return purchasable


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
                            'field': u'purchasables'
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
                                'field': u'refundApplicationFee'
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
