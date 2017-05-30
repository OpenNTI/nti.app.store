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

from nti.app.store.utils import AbstractPostView

from nti.app.store.views import PayeezyPathAdapter

from nti.app.store.views.general_views import PriceOrderView as GeneralPriceOrderView 
from nti.app.store.views.general_views import PricePurchasableView as GeneralPricePurchasableView

from nti.app.store.views.view_mixin import BaseProcessorViewMixin
from nti.app.store.views.view_mixin import RefundPaymentViewMixin
from nti.app.store.views.view_mixin import GetProcesorConnectKeyViewMixin

from nti.base._compat import text_

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store.interfaces import IPaymentProcessor

from nti.store.payments.payeezy import PAYEEZY

from nti.store.payments.payeezy.interfaces import IPayeezyConnectKey

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

    hook = lambda s: s and request.nti_gevent_spawn(processor)
    transaction.get().addAfterCommitHook(hook)


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
