#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import sys
from datetime import date
from datetime import datetime

from requests.structures import CaseInsensitiveDict

from zope import component

from zope.event import notify

from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.store import MessageFactory as _

from nti.app.store.utils import is_valid_amount
from nti.app.store.utils import is_valid_pve_int
from nti.app.store.utils import AbstractPostView

from nti.common.string import is_true

from nti.dataserver.users.interfaces import checkEmailAddress

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.store.interfaces import IPurchaseOrder
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import IPurchasableChoiceBundle
from nti.store.interfaces import PurchaseAttemptSuccessful

from nti.store.store import get_purchasable
from nti.store.store import get_purchase_attempt
from nti.store.store import get_purchase_by_code
from nti.store.store import get_pending_purchases
from nti.store.store import create_purchase_attempt
from nti.store.store import register_purchase_attempt
from nti.store.store import get_gift_pending_purchases
from nti.store.store import create_gift_purchase_attempt
from nti.store.store import register_gift_purchase_attempt

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED


class BaseProcessorViewMixin(AbstractAuthenticatedView):

    processor = None
    key_interface = None

    def get_connect_key(self, params=None):
        params if params else self.request.params
        keyname = CaseInsensitiveDict(params).get('provider')
        result = component.queryUtility(self.key_interface, keyname)
        return result


class PostProcessorViewMixin(BaseProcessorViewMixin, AbstractPostView):
    pass


class GetProcesorConnectKeyViewMixin(BaseProcessorViewMixin):

    def __call__(self):
        result = self.get_connect_key()
        if result is None:
            raise hexc.HTTPNotFound(_(u'Provider not found.'))
        return result


# pricing no-auth/permission views


def price_order(order, processor):
    pricer = component.getUtility(IPurchasablePricer, name=processor)
    result = pricer.evaluate(order)
    return result


class PriceOrderViewMixin(AbstractAuthenticatedView,
                          ModeledContentUploadRequestUtilsMixin):

    content_predicate = IPurchaseOrder.providedBy

    def readCreateUpdateContentObject(self, *args, **kwargs):
        externalValue = self.readInput()
        result = find_factory_for(externalValue)()
        update_from_external_object(result, externalValue, notify=False)
        return result


# purchase views


class BasePaymentViewMixin(ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        result = super(BasePaymentViewMixin, self).readInput(value=value)
        result = CaseInsensitiveDict(result)
        return result

    def validatePurchasable(self, request, purchasable_id):
        purchasable = get_purchasable(purchasable_id)
        if purchasable is None:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a valid purchasable."),
                            'field': u'purchasables',
                            'value': purchasable_id
                        },
                        None)
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

    def validatePurchasables(self, request, values, purchasables=()):
        result = [self.validatePurchasable(request, p) for p in purchasables]
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
                            'field': u'purchasables'
                        },
                        None)
        elif isinstance(purchasables, six.string_types):
            purchasables = list(set(purchasables.split()))
        result['Purchasables'] = purchasables

        token = values.get('token', None)
        if not token:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a valid token."),
                            'field': u'token'
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
                            'field': u'amount'
                        },
                        None)
        if expected_amount is not None:
            expected_amount = float(expected_amount)
        else:
            expected_amount = None
        result['Amount'] = result['ExpectedAmount'] = expected_amount

        quantity = values.get('quantity', None)
        if quantity is not None and not is_valid_pve_int(quantity):
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Invalid quantity."),
                            'field': u'quantity'
                        },
                        None)
        quantity = int(quantity) if quantity else None
        result['Quantity'] = quantity

        description = values.get('description', None)
        result['Description'] = description
        return result

    def createPurchaseOrder(self, record):
        raise NotImplementedError()

    def createPurchaseAttempt(self, record):
        order = self.createPurchaseOrder(record)
        result = create_purchase_attempt(order,
                                         processor=self.processor,
                                         context=record.get('Context'))
        return result

    def registerPurchaseAttempt(self, purchase_attempt, record):
        purchase_id = register_purchase_attempt(purchase_attempt,
                                                self.username)
        return purchase_id

    @property
    def username(self):
        return self.remoteUser.username

    def processPurchase(self, purchase_attempt, record):
        raise NotImplementedError()

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


class GiftPreflightViewMixin(AbstractAuthenticatedView, BasePaymentViewMixin):

    def readInput(self, value=None):
        values = super(GiftPreflightViewMixin, self).readInput(value)
        values.pop('Quantity', None)  # ignore quantity
        return values

    def validatePurchasables(self, request, values, purchasables=()):
        result = super(GiftPreflightViewMixin, self).validatePurchasables(request, values, purchasables)
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
        record = super(GiftPreflightViewMixin, self).getPaymentRecord(request, values)
        creator = values.get('from') \
               or values.get('sender') \
               or values.get('creator')
        if not creator:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a sender email."),
                            'field': u'from'
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
                            'field': u'from',
                            'code': e.__class__.__name__
                        },
                        exc_info[2])
        record['From'] = record['Creator'] = creator

        sender = values.get('senderName') \
              or values.get('sender') \
              or values.get('from')
        record['SenderName'] = record['Sender'] = sender

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
                                'field': u'receiver',
                                'code': e.__class__.__name__
                            },
                            exc_info[2])
        record['Receiver'] = receiver

        name = values.get('to') \
            or values.get('receiver') \
            or values.get('receiverName')
        receiverName = record['To'] = record['ReceiverName'] = name

        immediate = values.get('immediate') or values.get('deliverNow')
        if is_true(immediate):
            if not receiver:
                raise_error(request,
                            hexc.HTTPUnprocessableEntity,
                            {
                                'message': _(u"Please provide a receiver email."),
                                'field': u'immediate'
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
                            'field': u'message'
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


class GiftProcessorViewMixin(GiftPreflightViewMixin):

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


def find_purchase(key):
    try:
        purchase = get_purchase_by_code(key)
    except ValueError:
        purchase = get_purchase_attempt(key)
    return purchase


class GeneratePurchaseInvoiceViewMixin(PostProcessorViewMixin):

    def __call__(self):
        values = self.readInput()
        trx_id = values.get('code') \
              or values.get('purchase ') \
              or values.get('purchaseId') \
              or values.get('transaction') \
              or values.get('transactionId ')
        if not trx_id:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a transaction id."),
                            'field': u'transaction'
                        },
                        None)

        purchase = find_purchase(trx_id)
        if purchase is None:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction not found."),
                            'field': u'transaction'
                        },
                        None)
        elif not purchase.has_succeeded():
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction was not successful."),
                            'field': u'transaction'
                        },
                        None)
        manager = component.getUtility(IPaymentProcessor, name=self.processor)
        payment_charge = manager.get_payment_charge(purchase)

        notify(PurchaseAttemptSuccessful(purchase,
                                         payment_charge,
                                         request=self.request))
        return hexc.HTTPNoContent()


class RefundPaymentViewMixin(PostProcessorViewMixin):

    def processInput(self, values=None):
        values = values or self.readInput()
        trx_id = values.get('code') \
              or values.get('purchase ') \
              or values.get('purchaseId') \
              or values.get('transaction') \
              or values.get('transactionId')
        if not trx_id:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a transaction id."),
                            'field': u'transaction'
                        },
                        None)

        purchase = find_purchase(trx_id)
        if purchase is None:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction not found."),
                            'field': u'transaction'
                        },
                        None)
        elif not purchase.has_succeeded():
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction was not successful."),
                            'field': u'transaction'
                        },
                        None)

        amount = values.get('amount', None)
        if amount is not None and not is_valid_amount(amount):
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a valid amount."),
                            'field': u'amount'
                        },
                        None)
        amount = float(amount) if amount is not None else None
        return purchase, amount
