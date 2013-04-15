#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from zope import component

from nti.store.payments.stripe.stripe_io import StripeIO
from nti.store.payments.stripe import interfaces as stripe_interfaces

from nti.appserver.tests.test_application import SharedApplicationTestBase, WithSharedApplicationMockDS

from hamcrest import (assert_that, is_, has_length, has_entry, has_key, greater_than_or_equal_to)

class TestApplicationStoreViews(SharedApplicationTestBase):

	set_up_packages = SharedApplicationTestBase.set_up_packages + (('purchasables.zcml', 'nti.appserver.tests'),)

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_purchasables(self):

		url = '/dataserver2/store/get_purchasables'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_length(1))
		assert_that(json_body[0]['NTIID'],
					is_("tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_stripe_key(self):
		url = '/dataserver2/store/get_stripe_connect_key'
		params = {'provider':'NTI-TEST'}
		res = self.testapp.get(url, params, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry(u'Alias', u'NTI-TEST'))
		assert_that(json_body, has_entry(u'Class', u'StripeConnectKey'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_validate_stripe_copoun(self):
		url = '/dataserver2/store/validate_stripe_coupon'
		params = {'coupon':'TESTCOUPON', 'amount':300, 'provider':'NTI-TEST'}
		res = self.testapp.post(url, params, status=200)
		json_body = res.json_body
		assert_that(json_body, has_length(2))
		assert_that(json_body, has_entry('NewAmount', 270.0))
		assert_that(json_body, has_key('Coupon'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_purchase_history(self):
		url = '/dataserver2/store/get_purchase_history'
		# params = {'coupon':'TESTCOUPON', 'amount':300}
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_length(greater_than_or_equal_to(0)))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_pending_purchases(self):
		url = '/dataserver2/store/get_pending_purchases'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_length(greater_than_or_equal_to(0)))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def xtest_post_stripe_payment(self):
		# create token
		stripe = component.queryUtility(stripe_interfaces.IStripeConnectKey, "NTI-TEST")
		t = StripeIO.create_stripe_token(number="5105105105105100",
										 exp_month="11",
										 exp_year="30",
										 cvc="542",
										 address="3001 Oak Tree #D16",
										 city="Norman",
										 zip="73072",
										 state="OK",
										 country="USA",
										 api_key=stripe.PrivateKey)

		url = '/dataserver2/store/post_stripe_payment'
		params = {'items':'tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"',
				  'amount': 300,
				  'token': t.id,
				  'provider': "NTI-TEST"}

		res = self.testapp.post(url, params=params, status=200)
		json_body = res.json_body
		import pprint
		pprint.pprint(json_body)
