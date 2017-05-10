#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import sys

from zope import component

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.store import MessageFactory as _

from nti.app.store.views import PayeezyPathAdapter

from nti.app.store.views.general_views import PricePurchasableView as GeneralPricePurchasableView

from nti.app.store.views.view_mixin import PriceOrderViewMixin
from nti.app.store.views.view_mixin import BaseProcessorViewMixin
from nti.app.store.views.view_mixin import RefundPaymentViewMixin
from nti.app.store.views.view_mixin import GetProcesorConnectKeyViewMixin

from nti.app.store.views.view_mixin import price_order

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.store import PricingException
from nti.store import InvalidPurchasable

from nti.store.interfaces import IPricingError
from nti.store.interfaces import IPaymentProcessor

from nti.store.payments.payeezy import PAYEEZY

from nti.store.payments.payeezy.interfaces import IPayeezyConnectKey

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED


class BasePayeezyView(BaseProcessorViewMixin):
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
class GetConnectKeyView(GetProcesorConnectKeyViewMixin,
                        BasePayeezyView):
    pass


# pricing


@view_config(name="PriceOrder")
@view_config(name="price_order")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=PayeezyPathAdapter,
               request_method='POST')
class PriceOrderView(PriceOrderViewMixin, BasePayeezyView):

    def _do_pricing(self, order):
        try:
            result = price_order(order, self.processor)
        except InvalidPurchasable:
            result = IPricingError(_(u"Invalid purchasable."))
        except PricingException as e:
            result = IPricingError(e)
        except Exception:
            raise
        return result

    def _do_call(self):
        order = self.readCreateUpdateContentObject()
        result = self._do_pricing(order)
        status = 422 if IPricingError.providedBy(result) else 200
        self.request.response.status_int = status
        return result


@view_config(name="PricePurchasable")
@view_config(name="price_purchasable")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               context=PayeezyPathAdapter,
               request_method='POST')
class PricePurchasableView(GeneralPricePurchasableView):
    pass


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
class RefundPaymentView(RefundPaymentViewMixin, BasePayeezyView):

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
