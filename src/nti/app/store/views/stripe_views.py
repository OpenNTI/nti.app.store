#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import sys
from datetime import date
from datetime import datetime
from functools import partial

from requests.structures import CaseInsensitiveDict

from zope import component

import transaction

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error as raise_error
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.store import MessageFactory as _
from nti.app.store import get_possible_site_names

from nti.app.store.utils import to_boolean
from nti.app.store.utils import is_valid_amount
from nti.app.store.utils import is_valid_pve_int
from nti.app.store.utils import is_valid_boolean

from nti.app.store.views import StorePathAdapter

from nti.app.store.views.view_mixin import BaseProcessorViewMixin
from nti.app.store.views.view_mixin import PostProcessorViewMixin
from nti.app.store.views.view_mixin import RefundPaymentViewMixin
from nti.app.store.views.view_mixin import GetProcesorConnectKeyViewMixin
from nti.app.store.views.view_mixin import GeneratePurchaseInvoiceViewMixin

from nti.app.store.views.view_mixin import price_order

from nti.base._compat import unicode_

from nti.common.string import is_true

from nti.dataserver import authorization as nauth
from nti.dataserver.users.interfaces import checkEmailAddress

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

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

from nti.store.store import get_purchasable
from nti.store.store import get_pending_purchases
from nti.store.store import create_purchase_attempt
from nti.store.store import register_purchase_attempt
from nti.store.store import get_gift_pending_purchases
from nti.store.store import create_gift_purchase_attempt
from nti.store.store import register_gift_purchase_attempt

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED


class BaseStripeView(BaseProcessorViewMixin):
    processor = STRIPE
    key_interface = IStripeConnectKey   


class PostStripeView(BaseStripeView, PostProcessorViewMixin):
    pass


@view_config(name="GetStripeConnectKey")
@view_config(name="get_connect_key") # TODO: remove
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='GET')
class GetStripeConnectKeyView(GetProcesorConnectKeyViewMixin, BaseStripeView):
    pass


# pricing no-auth/permission views


def perform_pricing(purchasable_id, quantity=None, coupon=None, processor=STRIPE):
    pricer = component.getUtility(IPurchasablePricer, name=processor)
    priceable = create_stripe_priceable(ntiid=purchasable_id,
                                        quantity=quantity,
                                        coupon=coupon)
    result = pricer.price(priceable)
    return result


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
                           ModeledContentUploadRequestUtilsMixin):

    content_predicate = IStripePurchaseOrder.providedBy

    def readCreateUpdateContentObject(self, *args, **kwargs):
        externalValue = self.readInput()
        result = find_factory_for(externalValue)()
        update_from_external_object(result, externalValue)
        return result

    def _do_call(self):
        order = self.readCreateUpdateContentObject()
        assert IStripePurchaseOrder.providedBy(order)
        if order.Coupon: # replace item coupons
            replace_items_coupon(order, None)
        result = _call_pricing_func(partial(price_order, order))
        status = 422 if IPricingError.providedBy(result) else 200
        self.request.response.status_int = status
        return result


@view_config(name="PricePurchasableWithStripeCoupon")
@view_config(name="price_purchasable_with_stripe_coupon")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class PricePurchasableWithStripeCouponView(PostStripeView):

    def price_purchasable(self, values=None):
        values = values or self.readInput()
        coupon = values.get('code') \
              or values.get('coupon') \
              or values.get('couponCode')
        purchasable_id = values.get('ntiid') \
                      or values.get('purchasable') \
                      or values.get('purchasableId') \
                      or values.get('purchasable_Id') or u''

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


# purchase views


@view_config(name="CreateStripeToken")
@view_config(name="create_stripe_token")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='POST')
class CreateStripeTokenView(PostStripeView):

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
                params[key] = unicode_(value)
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
                params[k] = unicode_(value)

        token = manager.create_token(**params)
        result = LocatedExternalDict(Token=token.id)
        return result


def process_purchase(manager, purchase_id, username, token, expected_amount,
                     stripe_key, request, site_names=()):
    logger.info("Processing purchase %s", purchase_id)
    manager.process_purchase(purchase_id=purchase_id, username=username,
                             token=token, expected_amount=expected_amount,
                             api_key=stripe_key.PrivateKey,
                             request=request,
                             site_names=site_names)


def addAfterCommitHook(manager, purchase_id, username, token, expected_amount,
                       stripe_key, request, site_names=()):

    processor = partial(process_purchase,
                        token=token,
                        request=request,
                        manager=manager,
                        username=username,
                        site_names=site_names,
                        stripe_key=stripe_key,
                        purchase_id=purchase_id,
                        expected_amount=expected_amount)

    hook = lambda s: s and request.nti_gevent_spawn(processor)
    transaction.get().addAfterCommitHook(hook)


class BasePaymentWithStripeView(ModeledContentUploadRequestUtilsMixin):

    processor = STRIPE

    KEYS = (('AllowVendorUpdates', 'allow_vendor_updates', bool),)

    def readInput(self, value=None):
        result = super(BasePaymentWithStripeView, self).readInput(value=value)
        result = CaseInsensitiveDict(result or {})
        return result

    def parseContext(self, values, purchasables=()):
        context = dict()
        for purchasable in purchasables:
            context['Purchasable'] = purchasable.NTIID  # pick last
            if purchasable.VendorInfo:
                vendor = to_external_object(purchasable.VendorInfo)
                context.update(vendor)

        # capture user context data
        data = CaseInsensitiveDict(values.get('Context') or {})
        for name, alias, klass in self.KEYS:
            value = data.get(name)
            value = data.get(alias) if value is None else value
            if value is not None:
                context[name] = klass(value)
        return context

    def validatePurchasable(self, request, purchasable_id):
        purchasable = get_purchasable(purchasable_id)
        if purchasable is None:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Please provide a valid purchasable."),
                            'field': 'purchasables',
                            'value': purchasable_id
                        },
                        None)
        return purchasable

    def validatePurchasables(self, request, values, purchasables=()):
        result = [self.validatePurchasable(request, p) for p in purchasables]
        return result

    def validateStripeKey(self, request, purchasables=()):
        result = None
        for purchasable in purchasables:
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
        return result

    def getPaymentRecord(self, request, values=None):
        values = values or self.readInput()
        result = CaseInsensitiveDict()
        purchasables = values.get('purchasable') \
            or values.get('purchasables') \
            or values.get('purchasableId')
        if not purchasables:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Please provide a purchasable."),
                            'field': 'purchasables'
                        },
                        None)
        elif isinstance(purchasables, six.string_types):
            purchasables = list(set(purchasables.split()))
        result['Purchasables'] = purchasables

        purchasables = self.validatePurchasables(request, values, purchasables)
        stripe_key = self.validateStripeKey(request, purchasables)
        result['StripeKey'] = stripe_key

        context = self.parseContext(values, purchasables)
        result['Context'] = context

        token = values.get('token', None)
        if not token:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Please provide a valid stripe token."),
                            'field': 'token'
                        },
                        None)
            raise hexc.HTTPUnprocessableEntity(_(u"No token provided"))
        result['Token'] = token

        expected_amount = values.get('amount') or values.get('expectedAmount')
        if expected_amount is not None and not is_valid_amount(expected_amount):
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Invalid expected amount."),
                            'field': 'amount'
                        },
                        None)
        expected_amount = float(
            expected_amount) if expected_amount is not None else None
        result['Amount'] = result['ExpectedAmount'] = expected_amount

        coupon = values.get('coupon', None)
        result['Coupon'] = coupon

        quantity = values.get('quantity', None)
        if quantity is not None and not is_valid_pve_int(quantity):
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Invalid quantity."),
                            'field': 'quantity'
                        },
                        None)
        quantity = int(quantity) if quantity else None
        result['Quantity'] = quantity

        description = values.get('description', None)
        result['Description'] = description
        return result

    def validateCoupon(self, request, record):
        coupon = record['Coupon']
        if coupon:
            manager = component.getUtility(IPaymentProcessor,
                                           name=self.processor)
            try:
                if not manager.validate_coupon(coupon):
                    raise_error(request,
                                hexc.HTTPUnprocessableEntity,
                                {    
                                    'message': _(u"Invalid coupon."),
                                    'field': 'coupon'
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
        return record

    def createPurchaseOrder(self, record):
        items = [create_stripe_purchase_item(p)
                 for p in record['Purchasables']]
        result = create_stripe_purchase_order(tuple(items),
                                              quantity=record['Quantity'],
                                              coupon=record['coupon'])
        return result

    def createPurchaseAttempt(self, record):
        order = self.createPurchaseOrder(record)
        result = create_purchase_attempt(order, 
                                         processor=self.processor,
                                         context=record['Context'])
        return result

    def registerPurchaseAttempt(self, purchase_attempt, record):
        raise NotImplementedError()

    @property
    def username(self):
        return None

    def processPurchase(self, purchase_attempt, record):
        purchase_id = self.registerPurchaseAttempt(purchase_attempt, record)
        logger.info("Purchase attempt (%s) created", purchase_id)

        token = record['Token']
        stripe_key = record['StripeKey']
        expected_amount = record['ExpectedAmount']

        request = self.request
        username = self.username
        site_names = get_possible_site_names(request, include_default=True)
        manager = component.getUtility(IPaymentProcessor, name=self.processor)

        # process purchase after commit
        addAfterCommitHook(token=token,
                           request=request,
                           manager=manager,
                           username=username,
                           site_names=site_names,
                           stripe_key=stripe_key,
                           purchase_id=purchase_id,
                           expected_amount=expected_amount)

        # return
        result = LocatedExternalDict({    
                    ITEMS: [purchase_attempt],
                      LAST_MODIFIED: purchase_attempt.lastModified
                 })
        return result

    def __call__(self):
        values = self.readInput()
        record = self.getPaymentRecord(self.request, values)
        purchase_attempt = self.createPurchaseAttempt(record)
        result = self.processPurchase(purchase_attempt, record)
        return result


@view_config(name="PostStripePayment")
@view_config(name="post_stripe_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=StorePathAdapter,
               request_method='POST')
class ProcessPaymentWithStripeView(AbstractAuthenticatedView, BasePaymentWithStripeView):

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

    @property
    def username(self):
        return self.remoteUser.username

    def registerPurchaseAttempt(self, purchase_attempt, record):
        purchase_id = register_purchase_attempt(purchase_attempt, 
                                                self.username)
        return purchase_id

    def __call__(self):
        username = self.username
        values = self.readInput()
        record = self.getPaymentRecord(self.request, values)
        purchase_attempt = self.createPurchaseAttempt(record)

        # check for any pending purchase for the items being bought
        purchases = get_pending_purchases(username, purchase_attempt.Items)
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


@view_config(name="GiftStripePaymentPreflight")
@view_config(name="gift_stripe_payment_preflight")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class GiftWithStripePreflightView(AbstractAuthenticatedView, 
                                  BasePaymentWithStripeView):

    def readInput(self, value=None):
        values = super(GiftWithStripePreflightView, self).readInput(value)
        values.pop('Quantity', None)  # ignore quantity
        return values

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
        creator = values.get('from') \
               or values.get('sender') \
               or values.get('creator')
        if not creator:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Please provide a sender email."),
                            'field': 'from'
                        },
                        None)

        try:
            checkEmailAddress(creator)
        except Exception as e:
            exc_info = sys.exc_info()
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Please provide a valid sender email."),
                            'field': 'from',
                            'code': e.__class__.__name__
                        },
                        exc_info[2])
        record['From'] = record['Creator'] = creator

        record['SenderName'] = record['Sender'] = \
               values.get('senderName') \
            or values.get('sender') \
            or values.get('from')

        receiver = values.get('receiver')
        if receiver:
            try:
                checkEmailAddress(receiver)
            except Exception as e:
                exc_info = sys.exc_info()
                raise_error(request,
                            hexc.HTTPUnprocessableEntity,
                            {    
                                'message': _(u"Please provide a valid receiver email."),
                                'field': 'receiver',
                                'code': e.__class__.__name__
                            },
                            exc_info[2])
        record['Receiver'] = receiver
        receiverName = record['To'] = record['ReceiverName'] = \
                   values.get('to') \
                or values.get('receiverName') \
                or values.get('receiver')

        immediate = values.get('immediate') or values.get('deliverNow')
        if is_true(immediate):
            if not receiver:
                raise_error(request,
                            hexc.HTTPUnprocessableEntity,
                            {    
                                'message': _(u"Please provide a receiver email."),
                                'field': 'immediate'
                            },
                            None)
            today = date.today()
            now = datetime(year=today.year, month=today.month, day=today.day)
            record['DeliveryDate'] = now
        else:
            record['DeliveryDate'] = None
        record['Immediate'] = bool(immediate)

        message = record['Message'] = values.get('message')
        if (message or receiverName) and not receiver:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u"Please provide a receiver email."),
                            'field': 'message'
                        },
                        None)
        return record

    @property
    def username(self):
        return None

    def createPurchaseAttempt(self, record):
        pass

    def registerPurchaseAttempt(self, purchase_attempt, record):
        pass

    def __call__(self):
        values = self.readInput()
        request = self.request
        record = self.getPaymentRecord(request, values)
        self.validateCoupon(request, record)
        return record


@view_config(name="GiftStripePayment")
@view_config(name="gift_stripe_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=StorePathAdapter,
               request_method='POST')
class GiftWithStripeView(GiftWithStripePreflightView):

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
class GeneratePurchaseInvoiceWitStripeView(GeneratePurchaseInvoiceViewMixin,
                                           BaseStripeView):
    pass


# refund


def refund_purchase(purchase, amount, refund_application_fee=None, request=None):
    manager = component.getUtility(IPaymentProcessor, name=STRIPE)
    return manager.refund_purchase(purchase, 
                                   amount=amount,
                                   request=request,
                                   refund_application_fee=refund_application_fee,)


@view_config(name="RefundPaymentWithStripe")
@view_config(name="refund_payment_with_stripe")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=StorePathAdapter,
               request_method='POST')
class RefundPaymentWithStripeView(RefundPaymentViewMixin, BaseStripeView):
    
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
