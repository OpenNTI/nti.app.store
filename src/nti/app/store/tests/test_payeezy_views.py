#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import none
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import contains
from hamcrest import has_item
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than_or_equal_to
does_not = is_not

import fudge

import anyjson as json

from nti.app.store.views.payeezy_views import process_purchase

from nti.externalization.externalization import to_external_object

from nti.store import PricingException

from nti.store.purchase_order import create_purchase_item
from nti.store.purchase_order import create_purchase_order

from nti.app.store.tests import ApplicationStoreTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS


class MockRunner(object):

    def __call__(self, func, *args, **kwargs):
        return func()


def do_purchase(manager, purchase_id, username, token,
                card_type, cardholder_name, card_expiry, expected_amount,
                payeezy_key, request, site_name=None):
    result = process_purchase(token=token,
                              manager=manager,
                              request=request,
                              username=username,
                              card_type=card_type,
                              card_expiry=card_expiry,
                              purchase_id=purchase_id,
                              payeezy_key=payeezy_key,
                              expected_amount=expected_amount,
                              cardholder_name=cardholder_name)
    return result



class TestPayeezyViews(ApplicationLayerTest):

    layer = ApplicationStoreTestLayer

    purchasable_id = u"tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_price_purchasable(self):
        url = '/dataserver2/store/payeezy/@@price_purchasable'
        params = {'purchasableId': self.purchasable_id, 'quantity': 2}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=200)
        json_body = res.json_body
        assert_that(json_body, has_entry('Quantity', 2))
        assert_that(json_body, has_entry('Amount', 300.0))
        assert_that(json_body, has_entry('Currency', 'USD'))
        assert_that(json_body, has_entry('PurchasePrice', 600.0))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_price_order(self):
        item = create_purchase_item(self.purchasable_id, quantity=2)
        order = create_purchase_order((item,))

        body = to_external_object(order)
        url = '/dataserver2/store/payeezy/@@price_order'

        res = self.testapp.post_json(url, body, status=200)
        json_body = res.json_body
        assert_that(json_body, has_entry('Currency', 'USD'))
        assert_that(json_body, has_entry('Class', 'PricingResults'))
        assert_that(json_body,
                    has_entry('Items', contains(has_entry('Amount', 300.0))))
        assert_that(json_body,
                    has_entry('Items', contains(has_entry('Currency', 'USD'))))
        assert_that(json_body,
                    has_entry('Items', contains(has_entry('PurchasePrice', 600.0))))
        assert_that(json_body,
                    has_entry('Items', contains(has_entry('Quantity', 2))))
        assert_that(json_body, has_entry('TotalPurchasePrice', 600.0))
        assert_that(json_body, has_entry('TotalNonDiscountedPrice', 600.0))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.general_views.perform_pricing')
    def test_price_purchasable_pricing_exception(self, mock_pr):

        mock_pr.is_callable().with_args().raises(PricingException("Aizen"))

        url = '/dataserver2/store/payeezy/@@price_purchasable'
        params = {'coupon': '123', 'purchasableId': self.purchasable_id}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=422)
        json_body = res.json_body
        assert_that(json_body, has_entry('Type', 'PricingError'))
        assert_that(json_body, has_entry('Message', 'Aizen'))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_create_token(self):
        url = '/dataserver2/store/payeezy/@@create_token'
        params = {
            'provider': 'CMU',
            'card_cvv': '019',
            'card_type': 'visa',
            'card_expiry': '0930',
            'card_number': '4012000033330026',
            'cardholder_name': 'Ichigo Kurosaki',
            # optional
            'city': 'Norman',
            'zip': '73072',
            'state': 'OK',
            'street': '3001 Oak Tree Ave #F6',
            'country': 'USA',
        }
        body = json.dumps(params)
        res = self.testapp.post(url, body, status=200)
        json_body = res.json_body
        assert_that(json_body,
                    has_entry('MimeType', 'application/vnd.nextthought.store.payeezyfdtoken'))
        assert_that(json_body,
                    has_entry('correlation_id', is_not(none())))
        assert_that(json_body,
                    has_entry('type', 'visa'))
        assert_that(json_body,
                    has_entry('value', is_not(none())))

    def _create_fake_charge(self, amount):
        token = {
            'token_data': {
                'cardholder_name': u'Ichigo Kurosaki'
            },
            'value': u"9211263973560026"
        }
        charge = {
            'token': token,
            'transaction_id': u'Xcution',
            'correlation_id': u'124.9616325598760',
            'transaction_tag': u'Fullbring',
            'amount': amount,
            'currency': u'USD',
            
        }
        return charge

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.payeezy_views.addAfterCommitHook')
    @fudge.patch('nti.store.payments.payeezy.processor.purchase.execute_charge')
    @fudge.patch('nti.store.payments.payeezy.processor.purchase.get_transaction_runner')
    def test_post_payment(self, mock_hook, mock_exe, mock_runner):
        mock_hook.is_callable().with_args().calls(do_purchase)
        mock_runner.is_callable().with_args().returns(MockRunner())
        
        charge = self._create_fake_charge(300)
        mock_exe.is_callable().with_args().returns(charge)
        
        url = '/dataserver2/store/payeezy/@@post_payment'
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'card_type': 'visa',
                  'card_expiry': '0930',
                  'cardholder_name': 'Ichigo Kurosaki',
                  'token': "9211263973560026"}
        body = json.dumps(params)
        res = self.testapp.post(url, body, status=200)
        json_body = res.json_body

        assert_that(json_body, has_key('Items'))
        assert_that(json_body,
                    has_entry('Last Modified', greater_than_or_equal_to(0)))
        
        items = json_body['Items']
        assert_that(items, has_length(1))

        assert_that(items[0], has_entry('Class', 'PurchaseAttempt'))
        assert_that(items[0], has_entry('State', 'Success'))
        assert_that(items[0], has_entry('Processor', 'payeezy'))
        assert_that(items[0], has_entry('PayeezyTokenType', 'visa'))
        assert_that(items[0], has_entry('PayeezyTokenID', '9211263973560026'))
        assert_that(items[0], has_entry('PayeezyTransactionID', 'Xcution'))
        assert_that(items[0], has_entry('ID', is_not(none())))
        assert_that(items[0], has_entry('TransactionID', is_not(none())))
        assert_that(items[0],
                    has_entry('Order', has_entry('Items', has_length(1))))
        assert_that(items[0],
                    has_entry('Pricing', has_entry('Items', has_length(1))))

        pid = items[0]['ID']
        url = '/dataserver2/store/@@get_purchase_attempt'
        params = {'purchase': pid}
        res = self.testapp.get(url, params=params, status=200)
        assert_that(res.json_body, has_entry('Items',
                                             has_item(has_entry('Class', 'PurchaseAttempt'))))
    