#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
does_not = is_not

import csv
import fudge
import anyjson as json
from cStringIO import StringIO

from nti.dataserver.users import User

from nti.store.store import get_purchase_history

from nti.app.store.views.stripe_views import process_purchase

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.store.tests import ApplicationStoreTestLayer

from nti.dataserver.tests import mock_dataserver

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

class TestAdminViews(ApplicationLayerTest):

	layer = ApplicationStoreTestLayer

	purchasable_id = "tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"

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
	def test_delete_purchase_attempt(self, mock_aach, mock_cc, mock_gtr):
		mock_aach.is_callable().with_args().calls(do_purchase)
		mock_gtr.is_callable().with_args().returns(MockRunner())

		self._create_fakge_charge(300, mock_cc)
		url = '/dataserver2/store/@@post_stripe_payment'
		body = {'purchasableID':self.purchasable_id,
				'amount': 300,
				'token': "tok_1053"}
		body = json.dumps(body)
		res = self.testapp.post(url, body, status=200)
		pid = res.json_body['Items'][0]['ID']
		
		with mock_dataserver.mock_db_trans(self.ds):
			user = User.get_user(self.default_username)
			history = get_purchase_history(user, safe=False)
			assert_that(history, has_length(1))
		
		url = '/dataserver2/store/@@delete_purchase_attempt'
		body = {'purchase':pid}
		body = json.dumps(body)
		
		self.testapp.post(url, body, status=204)
		with mock_dataserver.mock_db_trans(self.ds):
			user = User.get_user(self.default_username)
			history = get_purchase_history(user, safe=False)
			assert_that(history, has_length(0))

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
	def test_delete_purchase_history(self, mock_aach, mock_cc, mock_gtr):
		mock_aach.is_callable().with_args().calls(do_purchase)
		mock_gtr.is_callable().with_args().returns(MockRunner())

		self._create_fakge_charge(300, mock_cc)
		url = '/dataserver2/store/@@post_stripe_payment'
		body = {'purchasableID':self.purchasable_id,
				'amount': 300,
				'token': "tok_1053"}
		body = json.dumps(body)
		self.testapp.post(url, body, status=200)
		with mock_dataserver.mock_db_trans(self.ds):
			user = User.get_user(self.default_username)
			history = get_purchase_history(user, safe=False)
			assert_that(history, has_length(1))
		
		url = '/dataserver2/store/@@delete_purchase_history'
		body = {'username':self.default_username}
		body = json.dumps(body)
		
		self.testapp.post(url, body, status=204)
		with mock_dataserver.mock_db_trans(self.ds):
			user = User.get_user(self.default_username)
			history = get_purchase_history(user, safe=False)
			assert_that(history, is_(none()))
			
	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
	def test_get_users_purchase_history(self, mock_aach, mock_cc, mock_gtr):
		mock_aach.is_callable().with_args().calls(do_purchase)
		mock_gtr.is_callable().with_args().returns(MockRunner())

		self._create_fakge_charge(300, mock_cc)
		url = '/dataserver2/store/@@post_stripe_payment'
		body = {'purchasableID':self.purchasable_id,
				'amount': 300,
				'token': "tok_1053"}
		body = json.dumps(body)
		self.testapp.post(url, body, status=200)
		
		url = '/dataserver2/store/@@get_users_purchase_history'
		params = {'username':self.default_username,
				  'purchasable':self.purchasable_id}
		res = self.testapp.get(url, params, status=200)
		stream = StringIO(res.text)
		reader = csv.reader(stream)
		lines = list(reader)
		assert_that(lines, has_length(2))

	@WithSharedApplicationMockDS(users=True, testapp=True)	
	@fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
	def test_generate_purchase_invoice(self, mock_aach, mock_cc, mock_gtr):
		mock_aach.is_callable().with_args().calls(do_purchase)
		mock_gtr.is_callable().with_args().returns(MockRunner())

		self._create_fakge_charge(300, mock_cc)
		url = '/dataserver2/store/@@post_stripe_payment'
		body = {'purchasableID':self.purchasable_id,
				'amount': 300,
				'token': "tok_1053"}
		body = json.dumps(body)
		res = self.testapp.post(url, body, status=200)
		pid = res.json_body['Items'][0]['ID']
		
		url = '/dataserver2/store/@@generate_purchase_invoice'
		body = {'purchase':pid}
		body = json.dumps(body)
		
		self.testapp.post(url, body, status=204)

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
	@fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
	def test_get_users_gift_history(self, mock_aach, mock_cc, mock_gtr):
		mock_aach.is_callable().with_args().calls(do_purchase)
		mock_gtr.is_callable().with_args().returns(MockRunner())

		self._create_fakge_charge(199, mock_cc)
		url = '/dataserver2/store/@@gift_stripe_payment'
		params = {'purchasableID':self.purchasable_id,
				  'amount': 300,
				  'from': 'ichigo+@bleach.org',
				  'sender': 'Ichigo Kurosaki',
				  'receiver': 'aizen@bleach.org',
				  'To': 'Aizen Sosuke',
				  'message': 'Getsuga Tenshou',
				  'token': "tok_1053",
				  'immediate':True}
		body = json.dumps(params)

		self.testapp.post(url, body, status=200)
		url = '/dataserver2/store/get_users_gift_history'
		params = {'username':'ichigo+@bleach.org'}
		res = self.testapp.get(url, params, status=200)
		stream = StringIO(res.text)
		reader = csv.reader(stream)
		lines = list(reader)
		assert_that(lines, has_length(2))
		
	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_create_invitation_purchase(self):
		url = '/dataserver2/store/@@create_invitation_purchase'
		params = {'purchasable':self.purchasable_id,
				  'expiration': '2030-11-30',
				  'quantity':5}
		body = json.dumps(params)
		res = self.testapp.post(url, body, status=200)
		assert_that(res.json_body, has_entry('IsExpired', is_(False)))
		assert_that(res.json_body, has_entry('RemainingInvitations', is_(5)))
		assert_that(res.json_body, has_entry('ExpirationTime', is_not(none())))
		assert_that(res.json_body, has_entry('InvitationCode', is_not(none())))
		assert_that(res.json_body, has_entry('MimeType',
											 u'application/vnd.nextthought.store.invitationpurchaseattempt'))
		
		pid = res.json_body['ID']
		code = res.json_body['InvitationCode']
		for username, api in (('ichigo', '@@redeem_purchase_code'), 
							  ('azien', '@@redeem_gift')):
			with mock_dataserver.mock_db_trans(self.ds):
				self._create_user(username=username)
			
			environ = self._make_extra_environ(username=username)
			url = '/dataserver2/store/%s' % api
			params = {'code':code, 'AllowVendorUpdates':True, 
					  'purchasable':self.purchasable_id}
			res = self.testapp.post_json(url, params, status=200, extra_environ=environ)
			assert_that(res.json_body, has_entry('MimeType',
												 'application/vnd.nextthought.store.redeemedpurchaseattempt'))

		url = '/dataserver2/store/get_purchase_attempt/%s' % pid
		res = self.testapp.get(url, body, status=200)
		assert_that(res.json_body['Items'][0], has_entry('Consumers', has_length(2)))
