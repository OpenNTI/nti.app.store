#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import re
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

from nti.app.store.utils import AbstractPostView

from nti.app.store.views import get_current_site
from nti.app.store.views import PayeezyPathAdapter

from nti.app.store.views.general_views import PriceOrderView as GeneralPriceOrderView
from nti.app.store.views.general_views import PricePurchasableView as GeneralPricePurchasableView

from nti.app.store.views.view_mixin import BasePaymentViewMixin
from nti.app.store.views.view_mixin import BaseProcessorViewMixin
from nti.app.store.views.view_mixin import GiftPreflightViewMixin
from nti.app.store.views.view_mixin import RefundPaymentViewMixin
from nti.app.store.views.view_mixin import GetProcesorConnectKeyViewMixin

from nti.base._compat import text_

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasableChoiceBundle

from nti.store.payments.payeezy import PAYEEZY

from nti.store.payments.payeezy.interfaces import IPayeezyConnectKey

from nti.store.payments.utils import is_valid_credit_card_type

from nti.store.purchase_order import create_purchase_item
from nti.store.purchase_order import create_purchase_order

from nti.store.store import get_gift_pending_purchases
from nti.store.store import create_gift_purchase_attempt
from nti.store.store import register_gift_purchase_attempt

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED


class BasePayeezyViewMixin(BaseProcessorViewMixin):
    processor = PAYEEZY
    key_interface = IPayeezyConnectKey


# keys


@view_config(name="GetConnectKey")
@view_config(name="get_connect_key")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=PayeezyPathAdapter,
               request_method='GET')
class GetConnectKeyView(AbstractAuthenticatedView,
                        GetProcesorConnectKeyViewMixin,
                        BasePayeezyViewMixin):
    pass


# pricing


@view_config(name="PriceOrder")
@view_config(name="price_order")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=PayeezyPathAdapter,
               request_method='POST')
class PriceOrderView(GeneralPriceOrderView):
    processor = PAYEEZY


@view_config(name="PricePurchasable")
@view_config(name="price_purchasable")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=PayeezyPathAdapter,
               request_method='POST')
class PricePurchasableView(GeneralPricePurchasableView):
    processor = PAYEEZY


# purchase views


def process_purchase(manager, purchase_id, username, token,
                     card_type, cardholder_name, card_expiry, expected_amount,
                     payeezy_key, request, site_name=None):
    logger.info("Processing purchase %s", purchase_id)
    manager.process_purchase(token=token,
                             request=request,
                             username=username,
                             api_key=payeezy_key,
                             card_type=card_type,
                             card_expiry=card_expiry,
                             purchase_id=purchase_id,
                             expected_amount=expected_amount,
                             cardholder_name=cardholder_name)


def addAfterCommitHook(manager, purchase_id, username, token,
                       card_type, cardholder_name, card_expiry, expected_amount,
                       payeezy_key, request, site_name=None):

    processor = partial(process_purchase,
                        token=token,
                        manager=manager,
                        request=request,
                        username=username,
                        card_type=card_type,
                        site_name=site_name,
                        card_expiry=card_expiry,
                        payeezy_key=payeezy_key,
                        purchase_id=purchase_id,
                        cardholder_name=cardholder_name,
                        expected_amount=expected_amount)

    def hook(s): return s and request.nti_gevent_spawn(processor)
    transaction.get().addAfterCommitHook(hook)


def validate_payeezy_key(request, purchasables=()):
    result = None
    for purchasable in purchasables or ():
        provider = purchasable.Provider
        payeezy_key = component.queryUtility(IPayeezyConnectKey, provider)
        if payeezy_key is None:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid purchasable provider."),
                            'field': 'purchasables',
                            'value': provider
                        },
                        None)
        if result is None:
            result = payeezy_key
        elif result != payeezy_key:
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


def validate_payeezy_record(request, purchasables, record, values):
    # validate payeezy key
    payeezy_key = validate_payeezy_key(request, purchasables)
    record['PayeezyKey'] = payeezy_key
    # validate card type
    card_type = values.get('card_type') or values.get('CardType')
    if not is_valid_credit_card_type(card_type):
        raise_error(request,
                    hexc.HTTPUnprocessableEntity,
                    {
                        'message': _(u"Invalid card type."),
                        'field': 'card_type'
                    },
                    None)
    record['card_type'] = card_type
    # validate card expirty
    expiry = values.get('card_expiry') \
          or values.get('CardExpiry') \
          or values.get('expiry')
    expiry = str(expiry) if expiry else None
    if not expiry or not re.match(r'[0-9]{4}', expiry):
        raise_error(request,
                    hexc.HTTPUnprocessableEntity,
                    {
                        'message': _(u"Invalid card expirty."),
                        'field': 'card_expiry'
                    },
                    None)
    record['card_expiry'] = text_(expiry[:4])
    # validate card holder name
    name = values.get('cardholder_name') \
        or values.get('CardHolderName') \
        or values.get('name')
    if not name:
        raise_error(request,
                    hexc.HTTPUnprocessableEntity,
                    {
                        'message': _(u"Invalid card holder name."),
                        'field': 'cardholder_name'
                    },
                    None)
    record['cardholder_name'] = name
    return record


class BasePaymentWithPayeezyView(BasePaymentViewMixin):

    processor = PAYEEZY
    
    def getPaymentRecord(self, request, values=None):
        values = values or self.readInput()
        record = BasePaymentViewMixin.getPaymentRecord(self, request, values)
        purchasables = self.resolvePurchasables(record['Purchasables'])
        return validate_payeezy_record(request, purchasables, record, values)

    def createPurchaseOrder(self, record):
        purchasables = record['Purchasables']
        items = tuple(create_purchase_item(p) for p in purchasables)
        result = create_purchase_order(items, quantity=record['Quantity'])
        return result

    def processPurchase(self, purchase_attempt, record):
        purchase_id = self.registerPurchaseAttempt(purchase_attempt, record)
        logger.info("Purchase attempt (%s) created", purchase_id)

        token = record['Token']
        card_type = record['card_type']
        card_expiry = record['card_expiry']
        cardholder_name = record['cardholder_name']

        payeezy_key = record['PayeezyKey']
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
                           payeezy_key=payeezy_key,
                           purchase_id=purchase_id,
                           card_type=card_type,
                           card_expiry=card_expiry,
                           cardholder_name=cardholder_name,
                           expected_amount=expected_amount)

        # return
        result = LocatedExternalDict({
            ITEMS: [purchase_attempt],
            LAST_MODIFIED: purchase_attempt.lastModified
        })
        return result


@view_config(name="PostPayment")
@view_config(name="post_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=PayeezyPathAdapter,
               request_method='POST')
class ProcessPaymentView(AbstractPostView, BasePaymentWithPayeezyView):

    def validatePurchasable(self, request, purchasable_id):
        purchasable = super(ProcessPaymentView, self).validatePurchasable(request, purchasable_id)
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


@view_config(name="gift_payment_preflight")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=PayeezyPathAdapter,
               request_method='POST')
class GiftPreflightView(AbstractPostView, GiftPreflightViewMixin):

    processor = PAYEEZY

    def validatePurchasables(self, request, values, purchasables=()):
        result = super(GiftPreflightView, self).validatePurchasables(request, values, purchasables)
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
        record = super(GiftPreflightView, self).getPaymentRecord(request, values)
        purchasables = self.resolvePurchasables(record['Purchasables'])
        return validate_payeezy_record(request, purchasables, record, values)

    @property
    def username(self):
        return None

    def __call__(self):
        values = self.readInput()
        request = self.request
        record = self.getPaymentRecord(request, values)
        return record


@view_config(name="GiftPayment")
@view_config(name="gift_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=PayeezyPathAdapter,
               request_method='POST')
class GiftPaymentView(GiftPreflightView, BasePaymentWithPayeezyView):

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


# token views


@view_config(name="CreateToken")
@view_config(name="create_token")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               context=PayeezyPathAdapter,
               request_method='POST')
class CreateTokenView(AbstractPostView, BasePayeezyViewMixin):

    def __call__(self):
        values = self.readInput()
        payeezy_key = self.get_connect_key(values)
        if payeezy_key is None:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid provider key."),
                            'field': 'provider'
                        },
                        None)
        manager = component.getUtility(IPaymentProcessor, name=self.processor)

        params = {'api_key': payeezy_key}
        required = (('card_cvv', 'cvv', 'cvc'),
                    ('card_number', 'number', 'cc'),
                    ('card_type', 'card_type', 'type'),
                    ('card_expiry', 'card_expiry', 'expiry'),
                    ('cardholder_name', 'cardholder_name', 'name'))

        for k, p, a in required:
            value = values.get(k) or values.get(p) or values.get(a)
            if not value:
                raise_error(self.request,
                            hexc.HTTPUnprocessableEntity,
                            {
                                'message': _(u"Invalid value."),
                                'field': k,
                            },
                            None)
            params[k] = text_(value)

        # optional
        optional = (('city', 'city', 'city'),
                    ('zip_code', 'zip', 'address_zip'),
                    ('state',  'state', 'address_state'),
                    ('street_1', 'street', 'address_line1'),
                    ('street_2', 'street2', 'address_line2'),
                    ('country', 'country', 'address_country'))
        for k, p, a in optional:
            value = values.get(k) or values.get(p) or values.get(a)
            if value:
                params[k] = text_(value)
        street = ('%s\n%s' % (params.pop('street_1', None) or u'',
                              params.pop('street_2', None) or u'')).strip()
        if street:
            params['street'] = street
        token = manager.create_token(**params)
        return token


# refund


def refund_purchase(purchase, amount, request=None):
    manager = component.getUtility(IPaymentProcessor, name=PAYEEZY)
    return manager.refund_purchase(purchase,
                                   amount=amount,
                                   request=request)


@view_config(name="RefundPayment")
@view_config(name="refund_payment")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=PayeezyPathAdapter,
               request_method='POST')
class RefundPaymentView(AbstractPostView,
                        BasePayeezyViewMixin,
                        RefundPaymentViewMixin):

    def __call__(self):
        request = self.request
        purchase, amount = self.processInput()
        try:
            refund_purchase(purchase,
                            amount=amount,
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
