#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import
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
from hamcrest import has_property
from hamcrest import contains_string

from zope import component
from zope.component import eventtesting

import uuid
import stripe
import anyjson as json

from nti.appserver.tests.test_application import SharedApplicationTestBase, WithSharedApplicationMockDS
from nti.store.payments.stripe.tests.test_stripe_processor import create_purchase
from nti.dataserver.tests import mock_dataserver

from nti.store import interfaces as store_interfaces
from . import ITestMailDelivery

class TestApplicationStoreViews(SharedApplicationTestBase):

	set_up_packages = SharedApplicationTestBase.set_up_packages + (('store_config.zcml', 'nti.appserver.tests'),)

	@classmethod
	def setUpClass(cls):
		super(TestApplicationStoreViews, cls).setUpClass()
		cls.api_key = stripe.api_key
		stripe.api_key = u'sk_test_3K9VJFyfj0oGIMi7Aeg3HNBp'

	@classmethod
	def tearDownClass(cls):
		super(TestApplicationStoreViews, cls).tearDownClass()
		stripe.api_key = cls.api_key

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_purchasables(self):
		url = '/dataserver2/store/get_purchasables'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', 0))
		items = json_body['Items']
		assert_that(items, has_length(greater_than_or_equal_to(1)))

		item = items[0]
		assert_that(item, has_entry('NTIID', "tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"))
		assert_that(item, has_key('StripeConnectKey'))
		sck = item['StripeConnectKey']
		assert_that(sck, has_entry('Alias', 'CMU'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_stripe_key(self):
		url = '/dataserver2/store/get_stripe_connect_key'
		params = {'provider':'NTI-TEST'}
		res = self.testapp.get(url, params, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry(u'Alias', u'NTI-TEST'))
		assert_that(json_body, has_entry(u'Class', u'StripeConnectKey'))
		assert_that(json_body, has_entry(u'MimeType', u'application/vnd.nextthought.stripeconnectkey'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_price_item(self):
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
	def test_price_with_stripe_copoun(self):
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

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_purchase_history(self):
		url = '/dataserver2/store/get_purchase_history'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', greater_than_or_equal_to(0)))
		items = json_body['Items']
		assert_that(items, has_length(greater_than_or_equal_to(0)))

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

		items = self._get_pending_purchases()
		assert_that(items, has_length(greater_than_or_equal_to(1)))

	@WithSharedApplicationMockDS
	def test_confirmation_email(self):
		with mock_dataserver.mock_db_trans(self.ds):
			manager = component.getUtility(store_interfaces.IPaymentProcessor, name='stripe')
			# TODO: Is this actually hitting stripe external services? If
			# so, we need to mock that! This should be easy to do with fudge
			username, purchase_id, _, _ = create_purchase(self, item='tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers',
														  amount=300 * 5,
														  quantity=5,
														  manager=manager,
														  username='jason.madden@nextthought.com')


		assert_that(eventtesting.getEvents(store_interfaces.IPurchaseAttemptSuccessful), has_length(1))
		mailer = component.getUtility( ITestMailDelivery )
		assert_that( mailer.queue, has_length( 1 ) ) # Not actually queueing yet
		msg = mailer.queue[0]
		# TODO: Testing the body
		# TODO: Testing the HTML

		assert_that( msg, has_property( 'body', contains_string( username ) ) )
		assert_that( msg, has_property( 'body', contains_string( 'Activation Key' ) ) )
		assert_that( msg, has_property( 'body', contains_string( '5x 04-630: Computer Science for Practicing Engineers - US$300.00 each' ) ) )
		assert_that( msg.body, does_not( contains_string( '\xa4300.00' ) ) )
#		import codecs
#		with codecs.open('/tmp/file.html', 'w', encoding='utf-8') as f:
#			f.write( msg.html )
#		print(msg.body)
#		print(msg.html)
		assert_that( msg, has_property( 'html', contains_string( username ) ) )
		assert_that( msg, has_property( 'html', contains_string( '04-630: Computer Science for Practicing Engineers' ) ) )
		assert_that( msg.html, contains_string( 'US$300.00' ) )
