#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import assert_that
from hamcrest import has_length
from hamcrest import has_entry
from hamcrest import has_key
from hamcrest import greater_than_or_equal_to
from hamcrest import none
from hamcrest import is_not
does_not = is_not

import uuid
import stripe
import anyjson as json

from nti.testing.matchers import is_empty

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from . import ApplicationStoreTestLayer

class TestApplicationStoreViews(ApplicationLayerTest):
	layer = ApplicationStoreTestLayer

	def setUp(self):
		super(TestApplicationStoreViews, self).setUp()
		self.api_key = stripe.api_key
		stripe.api_key = u'sk_test_3K9VJFyfj0oGIMi7Aeg3HNBp'

	def tearDown(self):
		stripe.api_key = self.api_key
		super(TestApplicationStoreViews, self).tearDown()

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_price_purchasable_with_stripe_coupon_quantity(self):
		url = '/dataserver2/store/price_purchasable_with_stripe_coupon'
		params = {'purchasableID':"tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers",
				  'quantity':2}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry('Quantity', 2))
		assert_that(json_body, has_entry('Amount', 300.0))
		assert_that(json_body, has_entry('Currency', 'USD'))
		assert_that(json_body, has_entry('PurchasePrice', 600.0))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_price_purchasable_with_stripe_coupon(self):
		code = str(uuid.uuid4())
		stripe.Coupon.create(percent_off=10, duration='forever', id=code)

		url = '/dataserver2/store/price_purchasable_with_stripe_coupon'
		params = {'coupon':code,
				  'purchasableID':"tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry('Quantity', 1))
		assert_that(json_body, has_entry('PurchasePrice', 270.0))
		assert_that(json_body, has_entry('NonDiscountedPrice', 300.0))
		assert_that(json_body, has_key('Coupon'))

	def _get_pending_purchases(self):
		url = '/dataserver2/store/get_pending_purchases'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', greater_than_or_equal_to(0)))
		items = json_body['Items']
		return items

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_pending_purchases(self):
		items = self._get_pending_purchases()
		assert_that(items, has_length(greater_than_or_equal_to(0)))

	def _create_stripe_token(self):
		url = '/dataserver2/store/create_stripe_token'
		params = dict(cc="5105105105105100",
					  exp_month="11",
					  exp_year="30",
					  cvc="542",
					  address="3001 Oak Tree #D16",
					  city="Norman",
					  zip="73072",
					  state="OK",
					  country="USA",
					  provider='NTI-TEST')
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry('Token', is_not(none())))
		return json_body['Token']

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_post_stripe_payment(self):
		# create token
		t = self._create_stripe_token()

		url = '/dataserver2/store/post_stripe_payment'
		params = {'purchasableID':'tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers',
				  'amount': 300,
				  'token': t}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)

		json_body = res.json_body

		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', greater_than_or_equal_to(0)))
		items = json_body['Items']
		assert_that(items, has_length(1))
		purchase = items[0]
		assert_that(purchase, has_key('Order'))
		assert_that(purchase['Order'], has_entry('Items', has_length(1)))

		import gevent

		items = self._get_pending_purchases()
		assert_that(items, has_length(greater_than_or_equal_to(1)))
		# And we can let the greenlet run which will empty out the queue
		gevent.sleep(0)
		items = self._get_pending_purchases()
		assert_that(items, is_empty() )
