#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than_or_equal_to
does_not = is_not

import fudge

import uuid
import stripe
import anyjson as json

from zope import interface

from nti.store import PricingException
from nti.store.payments.stripe import NoSuchStripeCoupon
from nti.store.payments.stripe import InvalidStripeCoupon
from nti.store.payments.stripe.interfaces import IStripeCoupon

from nti.app.store.views.stripe_views import process_purchase

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.store.tests import ApplicationStoreTestLayer

class MockRunner(object):

	def __call__(self, func, *args, **kwargs):
		return func()

def do_purchase(manager, purchase_id, username, token, expected_amount,
				stripe_key, request, site_names):
	result = process_purchase(token=token,
							  request=request,
							  manager=manager,
							  username=username,
							  site_names=site_names,
							  stripe_key=stripe_key,
							  purchase_id=purchase_id,
							  expected_amount=expected_amount)
	return result

class TestStripeViews(ApplicationLayerTest):

	layer = ApplicationStoreTestLayer

	purchasable_id = "tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"

	def setUp(self):
		super(TestStripeViews, self).setUp()
		self.api_key = stripe.api_key
		stripe.api_key = u'sk_test_3K9VJFyfj0oGIMi7Aeg3HNBp'

	def tearDown(self):
		stripe.api_key = self.api_key
		super(TestStripeViews, self).tearDown()

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_price_purchasable_with_stripe_coupon_quantity(self):
		url = '/dataserver2/store/price_purchasable_with_stripe_coupon'
		params = {'purchasableID':self.purchasable_id, 'quantity':2}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry('Quantity', 2))
		assert_that(json_body, has_entry('Amount', 300.0))
		assert_that(json_body, has_entry('Currency', 'USD'))
		assert_that(json_body, has_entry('PurchasePrice', 600.0))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.store.payments.stripe.stripe_pricing.get_coupon')
	def test_price_purchasable_with_stripe_coupon(self, mock_gc):

		code = str(uuid.uuid4())
		coupon = mock_gc.is_callable().with_args().returns_fake()
		coupon.has_attr(id=code)
		coupon.has_attr(percent_off=10)
		coupon.has_attr(duration='forever')
		coupon.has_attr(amount_off=None)
		coupon.has_attr(currency="USD")
		coupon.has_attr(duration_in_months=None)
		coupon.has_attr(redeem_by=None)
		coupon.has_attr(times_redeemed=None)
		coupon.has_attr(max_redemptions=None)
		interface.alsoProvides(coupon, IStripeCoupon)

		url = '/dataserver2/store/price_purchasable_with_stripe_coupon'
		params = {'coupon':code, 'purchasableID':self.purchasable_id}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)
		json_body = res.json_body
		assert_that(json_body, has_entry('Quantity', 1))
		assert_that(json_body, has_entry('PurchasePrice', 270.0))
		assert_that(json_body, has_entry('NonDiscountedPrice', 300.0))
		assert_that(json_body, has_key('Coupon'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.perform_pricing')
	def test_price_purchasable_with_invalid_coupon(self, mock_pr):

		mock_pr.is_callable().with_args().raises(InvalidStripeCoupon())

		url = '/dataserver2/store/price_purchasable_with_stripe_coupon'
		params = {'coupon':'123', 'purchasableID':self.purchasable_id}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=422)
		json_body = res.json_body
		assert_that(json_body, has_entry('Type', 'PricingError'))
		assert_that(json_body, has_entry('Message', 'Invalid coupon'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.perform_pricing')
	def test_price_purchasable_no_such_coupon(self, mock_pr):

		mock_pr.is_callable().with_args().raises(NoSuchStripeCoupon())

		url = '/dataserver2/store/price_purchasable_with_stripe_coupon'
		params = {'coupon':'123', 'purchasableID':self.purchasable_id}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=422)
		json_body = res.json_body
		assert_that(json_body, has_entry('Type', 'PricingError'))
		assert_that(json_body, has_entry('Message', 'Invalid coupon'))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.perform_pricing')
	def test_price_purchasable_pricing_exception(self, mock_pr):

		mock_pr.is_callable().with_args().raises(PricingException("Aizen"))

		url = '/dataserver2/store/price_purchasable_with_stripe_coupon'
		params = {'coupon':'123', 'purchasableID':self.purchasable_id}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=422)
		json_body = res.json_body
		assert_that(json_body, has_entry('Type', 'PricingError'))
		assert_that(json_body, has_entry('Message', 'Aizen'))

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

	def _create_fakge_charge(self, amount, mock_cc):
		card = fudge.Fake()
		card.has_attr(name="Steve")
		card.has_attr(last4=4242)
		card.has_attr(address_line1="1 Infinite Loop")
		card.has_attr(address_line2=None)
		card.has_attr(address_city="Cupertino")
		card.has_attr(address_state="CA")
		card.has_attr(address_zip="95014")
		card.has_attr(address_country="USA")

		charge = mock_cc.is_callable().with_args().returns_fake()
		charge.has_attr(id="charge_1046")
		charge.has_attr(paid=True)
		charge.has_attr(card=card)
		charge.has_attr(created=None)
		charge.has_attr(amount=amount*100.0)
		charge.has_attr(currency="USD")
		return charge

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
	def test_post_stripe_payment(self, mock_aach, mock_cc, mock_gtr):
		mock_aach.is_callable().with_args().calls(do_purchase)
		mock_gtr.is_callable().with_args().returns(MockRunner())

		self._create_fakge_charge(300, mock_cc)
		url = '/dataserver2/store/post_stripe_payment'
		params = {'purchasableID':self.purchasable_id,
				  'amount': 300,
				  'token': "tok_1053"}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)
		json_body = res.json_body

		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', greater_than_or_equal_to(0)))

		items = json_body['Items']
		assert_that(items, has_length(1))
		assert_that(items[0], has_entry('Class', 'PurchaseAttempt'))
		assert_that(items[0], has_entry('State', 'Success'))
		assert_that(items[0], has_entry('ChargeID', 'charge_1046'))
		assert_that(items[0], has_entry('TokenID', 'tok_1053'))
		assert_that(items[0], has_entry('ID', is_not(none())))
		assert_that(items[0], has_entry('Order', has_entry('Items', has_length(1))))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
	def test_gift_stripe_payment(self, mock_aach, mock_cc, mock_gtr):
		mock_aach.is_callable().with_args().calls(do_purchase)
		mock_gtr.is_callable().with_args().returns(MockRunner())

		self._create_fakge_charge(199, mock_cc)
		url = '/dataserver2/store/gift_stripe_payment'
		params = {'purchasableID':self.purchasable_id,
				  'amount': 300,
				  'from': 'ichigo@bleach.org',
				  'sender': 'Ichigo Kurosaki',
				  'receiver': 'aizen@bleach.org',
				  'To': 'Aizen Sosuke',
				  'message': 'Getsuga Tenshou',
				  'token': "tok_1053",
				  'immediate':True}
		body = json.dumps(params)

		res = self.testapp.post(url, body, status=200)
		json_body = res.json_body

		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', greater_than_or_equal_to(0)))

		items = json_body['Items']
		assert_that(items, has_length(1))
		assert_that(items[0], has_entry('Order', has_entry('Items', has_length(1))))
		assert_that(items[0], has_entry('MimeType',
									    'application/vnd.nextthought.store.giftpurchaseattempt'))
		assert_that(items[0], has_entry('State', 'Success'))
		assert_that(items[0], has_entry('ChargeID', 'charge_1046'))
		assert_that(items[0], has_entry('TokenID', 'tok_1053'))
		assert_that(items[0], has_entry('ID', is_not(none())))
		assert_that(items[0], has_entry('NTIID', is_not(none())))
		assert_that(items[0], has_entry('Creator', is_('ichigo@bleach.org')))
		assert_that(items[0], has_entry('SenderName', is_('Ichigo Kurosaki')))
		assert_that(items[0], has_entry('ReceiverName', is_('Aizen Sosuke')))
		assert_that(items[0], has_entry('DeliveryDate', is_not(none())))

		url = '/dataserver2/store/get_gift_purchase_attempt'
		params ={ "purchaseID":items[0]['NTIID'],
				  'creator': 'ichigo@bleach.org' }
		self.testapp.get(url, params=params, status=200)

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_invalid_post_stripe_payment(self):
		url = '/dataserver2/store/post_stripe_payment'
		params = {'purchasableID':'not found',
				  'amount': 300,
				  'token': 'xyz'}
		body = json.dumps(params)
		self.testapp.post(url, body, status=422)

		params = {'purchasableID':self.purchasable_id,
				  'amount': 300}
		body = json.dumps(params)
		self.testapp.post(url, body, status=422)
