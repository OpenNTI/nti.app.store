#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import none
from hamcrest import is_not
from hamcrest import contains
from hamcrest import has_entry
from hamcrest import assert_that
does_not = is_not

import fudge

import anyjson as json

from nti.externalization.externalization import to_external_object

from nti.store import PricingException

from nti.store.purchase_order import create_purchase_item
from nti.store.purchase_order import create_purchase_order

from nti.app.store.tests import ApplicationStoreTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS


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
