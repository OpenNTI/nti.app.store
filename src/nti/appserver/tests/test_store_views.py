#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from nti.appserver.tests.test_application import SharedApplicationTestBase, WithSharedApplicationMockDS

from hamcrest import (assert_that, is_, has_length, has_entry)

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
	def test_validate_stripe_copoun(self):
		url = '/dataserver2/store/validate_stripe_coupon'
		params = {'coupon':'TESTCOUPON', 'amount':300, 'provider':'NTI-TEST'}
		res = self.testapp.post(url, params, status=200)
		json_body = res.json_body
		assert_that(json_body, has_length(2))
		assert_that(json_body, has_entry('Amount', 270.0))
		assert_that(json_body, has_entry('Coupon', 'TESTCOUPON'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_purchase_history(self):
		url = '/dataserver2/store/get_purchase_history'
		# params = {'coupon':'TESTCOUPON', 'amount':300}
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_length(0))

