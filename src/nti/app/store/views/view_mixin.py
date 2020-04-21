#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import six
import sys
from datetime import date
from datetime import datetime

from requests.structures import CaseInsensitiveDict

from zope import component

from zope.event import notify

from pyramid import httpexceptions as hexc

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.store import MessageFactory as _

from nti.app.store.utils import is_valid_amount
from nti.app.store.utils import is_valid_pve_int

from nti.common.string import is_true

from nti.dataserver.users.interfaces import checkEmailAddress

from nti.externalization.externalization import to_external_object

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

logger = __import__('logging').getLogger(__name__)


class BaseProcessorViewMixin(object):

    processor = None
    key_interface = None

    def get_connect_key(self, params=None):
        params = params or self.request.params
        keyname = CaseInsensitiveDict(params).get('provider')
        if keyname: # check key
            return component.queryUtility(self.key_interface, keyname)
        return None


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


class PriceOrderViewMixin(ModeledContentUploadRequestUtilsMixin):

    content_predicate = IPurchaseOrder.providedBy

    def _do_pricing(self, order):
        raise NotImplementedError()

    def readCreateUpdateContentObject(self, *unused_args, **unused_kwargs):
        externalValue = self.readInput()
        result = find_factory_for(externalValue)()
        update_from_external_object(result, externalValue, notify=False)
        return result


# purchase views


class BasePaymentViewMixin(ModeledContentUploadRequestUtilsMixin):

    processor = None
    KEYS = (('AllowVendorUpdates', 'allow_vendor_updates', bool),)

    def readInput(self, value=None):
        result = super(BasePaymentViewMixin, self).readInput(value=value)
        result = CaseInsensitiveDict(result)
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

    def validatePurchasables(self, request, unused_values, purchasables=()):
        result = [self.validatePurchasable(request, p) for p in purchasables]
        return result

    def resolvePurchasables(self, purchasables=()):
        result = [get_purchasable(p) for p in purchasables or ()]
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

        context = self.parseContext(values, purchasables)
        result['Context'] = context

        token = values.get('token', None)
        if not token:
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a valid token."),
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
                            'field': 'quantity'
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

    def registerPurchaseAttempt(self, purchase_attempt, unused_record):
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


class GiftPreflightViewMixin(BasePaymentViewMixin):

    processor = None

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
                            'field': 'purchasables'
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
                            'field': 'from'
                        },
                        None)

        if not checkEmailAddress(creator):
            exc_info = sys.exc_info()
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a valid sender email."),
                            'field': 'from',
                            'code': 'EmailAddressInvalid'
                        },
                        exc_info[2])
        record['From'] = record['Creator'] = creator

        sender = values.get('senderName') \
              or values.get('sender') \
              or values.get('from')
        record['SenderName'] = record['Sender'] = sender

        receiver = values.get('receiver')
        if receiver:
            if not checkEmailAddress(receiver):
                exc_info = sys.exc_info()
                raise_error(request,
                            hexc.HTTPUnprocessableEntity,
                            {
                                'message': _(u"Please provide a valid receiver email."),
                                'field': 'receiver',
                                'code': 'EmailAddressInvalid'
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


class GeneratePurchaseInvoiceViewMixin(object):

    def _do_call(self):
        values = self.readInput()
        trx_id = values.get('code') \
              or values.get('purchase') \
              or values.get('purchaseId') \
              or values.get('transaction') \
              or values.get('transactionId ')
        if not trx_id:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a transaction id."),
                            'field': 'transaction'
                        },
                        None)

        purchase = find_purchase(trx_id)
        if purchase is None:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction not found."),
                            'field': 'transaction'
                        },
                        None)
        elif not purchase.has_succeeded():
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction was not successful."),
                            'field': 'transaction'
                        },
                        None)
        manager = component.getUtility(IPaymentProcessor, name=purchase.Processor)
        payment_charge = manager.get_payment_charge(purchase)

        notify(PurchaseAttemptSuccessful(purchase,
                                         payment_charge,
                                         request=self.request))
        return hexc.HTTPNoContent()

    def __call__(self):
        return self._do_call()


class RefundPaymentViewMixin(object):

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
                            'field': 'transaction'
                        },
                        None)

        purchase = find_purchase(trx_id)
        if purchase is None:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction not found."),
                            'field': 'transaction'
                        },
                        None)
        elif not purchase.has_succeeded():
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Transaction was not successful."),
                            'field': 'transaction'
                        },
                        None)

        amount = values.get('amount', None)
        if amount is not None and not is_valid_amount(amount):
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Please provide a valid amount."),
                            'field': 'amount'
                        },
                        None)
        amount = float(amount) if amount is not None else None
        return purchase, amount
