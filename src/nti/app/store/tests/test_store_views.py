#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than_or_equal_to
does_not = is_not

import stripe
from urllib import quote

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.store.tests import ApplicationStoreTestLayer

class TestStoreViews(ApplicationLayerTest):

	layer = ApplicationStoreTestLayer

	def setUp(self):
		super(TestStoreViews, self).setUp()
		self.api_key = stripe.api_key
		stripe.api_key = u'sk_test_3K9VJFyfj0oGIMi7Aeg3HNBp'

	def tearDown(self):
		stripe.api_key = self.api_key
		super(TestStoreViews, self).tearDown()

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_purchasables(self):
		url = '/dataserver2/store/@@get_purchasables'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', 0))
		items = json_body['Items']
		assert_that(items, has_length(greater_than_or_equal_to(1)))
		
		ntiid = "tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"
		sck = None
		found = False
		for item in items:
			if item.get('NTIID') == ntiid:
				sck = item.get('StripeConnectKey')
				found = True
				break

		assert_that(found, is_(True))
		assert_that(sck, has_entry('Alias', 'CMU'))
		
		url = '/dataserver2/store/@@get_purchasables?purchasables=%s' % quote(ntiid)
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry('Items', has_length(1)))
		item_body = json_body['Items'][0]
		self.require_link_href_with_rel(item_body, 'price')
		self.require_link_href_with_rel(item_body, 'post_stripe_payment')
		self.require_link_href_with_rel(item_body, 'create_stripe_token')
		self.require_link_href_with_rel(item_body, 'get_stripe_connect_key')
		self.require_link_href_with_rel(item_body, 'price_purchasable')
		self.require_link_href_with_rel(item_body, 'price_purchasable_with_stripe_coupon')
		
	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_purchase_history(self):
		url = '/dataserver2/store/@@get_purchase_history'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', greater_than_or_equal_to(0)))
		items = json_body['Items']
		assert_that(items, has_length(greater_than_or_equal_to(0)))

	def _get_pending_purchases(self):
		url = '/dataserver2/store/@@get_pending_purchases'
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
