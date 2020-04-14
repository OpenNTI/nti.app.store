#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904
from collections import OrderedDict

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import contains
from hamcrest import has_item
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than_or_equal_to
from hamcrest import not_
from hamcrest import not_none
from hamcrest import starts_with
from hamcrest import has_properties
from hamcrest import has_entries

from zope.component.hooks import getSite

from zope.securitypolicy.interfaces import IPrincipalRoleManager

from nti.app.store import DEFAULT_STRIPE_KEY_ALIAS

from nti.store.payments.stripe.model import PersistentStripeConnectKey

does_not = is_not

import uuid

import fudge

import stripe

import simplejson as json

from six.moves import urllib_parse

from zope import interface

from nti.app.store.views.stripe_views import process_purchase

from nti.app.store.tests import ApplicationStoreTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.authorization import ROLE_SITE_ADMIN

from nti.dataserver.tests import mock_dataserver

from nti.externalization.externalization import to_external_object

from nti.store import PricingException

from nti.store.payments.stripe import NoSuchStripeCoupon
from nti.store.payments.stripe import InvalidStripeCoupon

from nti.store.payments.stripe.interfaces import IStripeCoupon

from nti.store.payments.stripe.storage import get_stripe_key_container

from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_item
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_order


class MockRunner(object):

    def __call__(self, func, *unused_args, **unused_kwargs):
        return func()


def do_purchase(manager, purchase_id, username, token, expected_amount,
                stripe_key, request, site_name=None):
    result = process_purchase(token=token,
                              request=request,
                              manager=manager,
                              username=username,
                              site_name=site_name,
                              stripe_key=stripe_key,
                              purchase_id=purchase_id,
                              expected_amount=expected_amount)
    return result


class TestStripeViews(ApplicationLayerTest):

    layer = ApplicationStoreTestLayer

    purchasable_id = u"tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"

    def setUp(self):
        super(TestStripeViews, self).setUp()
        self.api_key = stripe.api_key
        stripe.api_key = u'sk_test_3K9VJFyfj0oGIMi7Aeg3HNBp'

    def tearDown(self):
        stripe.api_key = self.api_key
        super(TestStripeViews, self).tearDown()

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_price_purchasable_with_stripe_coupon_quantity(self):
        url = '/dataserver2/store/@@price_purchasable_with_stripe_coupon'
        params = {'purchasableId': self.purchasable_id, 'quantity': 2}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=200)
        json_body = res.json_body
        assert_that(json_body, has_entry('Quantity', 2))
        assert_that(json_body, has_entry('Amount', 300.0))
        assert_that(json_body, has_entry('Currency', 'USD'))
        assert_that(json_body, has_entry('PurchasePrice', 600.0))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.store.payments.stripe.pricing.get_coupon')
    def test_price_purchasable_with_stripe_coupon(self, mock_gc):

        code = str(uuid.uuid4())
        coupon = mock_gc.is_callable().with_args().returns_fake()
        coupon.has_attr(id=code)
        coupon.has_attr(percent_off=10)
        coupon.has_attr(duration=u'forever')
        coupon.has_attr(amount_off=None)
        coupon.has_attr(currency=u"USD")
        coupon.has_attr(duration_in_months=None)
        coupon.has_attr(redeem_by=None)
        coupon.has_attr(times_redeemed=None)
        coupon.has_attr(max_redemptions=None)
        interface.alsoProvides(coupon, IStripeCoupon)

        url = '/dataserver2/store/@@price_purchasable_with_stripe_coupon'
        params = {'coupon': code, 'purchasableId': self.purchasable_id}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=200)
        json_body = res.json_body
        assert_that(json_body, has_entry('Quantity', 1))
        assert_that(json_body, has_entry('PurchasePrice', 270.0))
        assert_that(json_body, has_entry('NonDiscountedPrice', 300.0))
        assert_that(json_body, has_key('Coupon'))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_price_stripe_order(self):
        item = create_stripe_purchase_item(self.purchasable_id, quantity=2)
        order = create_stripe_purchase_order((item,))

        body = to_external_object(order)
        url = '/dataserver2/store/@@price_stripe_order'

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
    @fudge.patch('nti.app.store.views.stripe_views.perform_pricing')
    def test_price_purchasable_with_invalid_coupon(self, mock_pr):

        mock_pr.is_callable().with_args().raises(InvalidStripeCoupon())

        url = '/dataserver2/store/@@price_purchasable_with_stripe_coupon'
        params = {'coupon': '123', 'purchasableId': self.purchasable_id}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=422)
        json_body = res.json_body
        assert_that(json_body, has_entry('Type', 'PricingError'))
        assert_that(json_body, has_entry('Message', 'Invalid coupon.'))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.perform_pricing')
    def test_price_purchasable_no_such_coupon(self, mock_pr):

        mock_pr.is_callable().with_args().raises(NoSuchStripeCoupon())

        url = '/dataserver2/store/@@price_purchasable_with_stripe_coupon'
        params = {'coupon': '123', 'purchasableId': self.purchasable_id}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=422)
        json_body = res.json_body
        assert_that(json_body, has_entry('Type', 'PricingError'))
        assert_that(json_body, has_entry('Message', 'Invalid coupon.'))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.perform_pricing')
    def test_price_purchasable_pricing_exception(self, mock_pr):

        mock_pr.is_callable().with_args().raises(PricingException("Aizen"))

        url = '/dataserver2/store/@@price_purchasable_with_stripe_coupon'
        params = {'coupon': '123', 'purchasableId': self.purchasable_id}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=422)
        json_body = res.json_body
        assert_that(json_body, has_entry('Type', 'PricingError'))
        assert_that(json_body, has_entry('Message', 'Aizen'))

    def _get_pending_purchases(self):
        url = '/dataserver2/store/@@get_pending_purchases'
        res = self.testapp.get(url, status=200)
        json_body = res.json_body
        assert_that(json_body, has_key('Items'))
        assert_that(json_body,
                    has_entry('Last Modified', greater_than_or_equal_to(0)))
        items = json_body['Items']
        return items

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_get_pending_purchases(self):
        items = self._get_pending_purchases()
        assert_that(items, has_length(greater_than_or_equal_to(0)))

    def _create_fake_charge(self, amount, mock_cc):
        card = fudge.Fake()
        card.has_attr(name=u"Steve")
        card.has_attr(last4=4242)
        card.has_attr(address_line1=u"1 Infinite Loop")
        card.has_attr(address_line2=None)
        card.has_attr(address_city=u"Cupertino")
        card.has_attr(address_state=u"CA")
        card.has_attr(address_zip=u"95014")
        card.has_attr(address_country=u"USA")

        charge = mock_cc.is_callable().with_args().returns_fake()
        charge.has_attr(id=u"charge_1046")
        charge.has_attr(paid=True)
        charge.has_attr(card=card)
        charge.has_attr(created=None)
        charge.has_attr(amount=amount * 100.0)
        charge.has_attr(currency=u"USD")
        return charge

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
    @fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
    @fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
    def test_post_stripe_payment(self, mock_aach, mock_cc, mock_gtr):
        mock_aach.is_callable().with_args().calls(do_purchase)
        mock_gtr.is_callable().with_args().returns(MockRunner())

        self._create_fake_charge(300, mock_cc)
        url = '/dataserver2/store/@@post_stripe_payment'
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'token': "tok_1053"}
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
        assert_that(items[0], has_entry('ChargeID', 'charge_1046'))
        assert_that(items[0], has_entry('TokenID', 'tok_1053'))
        assert_that(items[0], has_entry('ID', is_not(none())))
        assert_that(items[0], has_entry('TransactionID', is_not(none())))
        assert_that(items[0],
                    has_entry('Order', has_entry('Items', has_length(1))))

        pid = items[0]['ID']
        url = '/dataserver2/store/@@get_purchase_attempt'
        params = {'purchase': pid}
        res = self.testapp.get(url, params=params, status=200)
        assert_that(res.json_body, has_entry('Items',
                                             has_item(has_entry('Class', 'PurchaseAttempt'))))

        url = '/dataserver2/store/@@get_purchase_attempt/%s' % pid
        res = self.testapp.get(url, status=200)
        assert_that(res.json_body, has_entry('Items',
                                             has_item(has_entry('Class', 'PurchaseAttempt'))))

        tid = items[0]['TransactionID']
        url = '/dataserver2/store/@@get_purchase_attempt/%s' % tid
        res = self.testapp.get(url, status=200)
        assert_that(res.json_body,
                    has_entry('Items',
                              has_item(has_entry('Class', 'PurchaseAttempt'))))

        url = '/dataserver2/store/@@get_purchase_attempt/foo'
        res = self.testapp.get(url, status=404)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
    @fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
    @fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
    def test_gift_stripe_payment(self, mock_aach, mock_cc, mock_gtr):
        mock_aach.is_callable().with_args().calls(do_purchase)
        mock_gtr.is_callable().with_args().returns(MockRunner())

        self._create_fake_charge(199, mock_cc)
        url = '/dataserver2/store/@@gift_stripe_payment'
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'from': 'ichigo+@bleach.org',
                  'sender': 'Ichigo Kurosaki',
                  'receiver': 'aizen@bleach.org',
                  'To': 'Aizen Sosuke',
                  'message': 'Getsuga Tenshou',
                  'token': "tok_1053",
                  'immediate': True}
        body = json.dumps(params)

        res = self.testapp.post(url, body, status=200)
        json_body = res.json_body

        assert_that(json_body, has_key('Items'))
        assert_that(json_body,
                    has_entry('Last Modified', greater_than_or_equal_to(0)))

        items = json_body['Items']
        assert_that(items, has_length(1))
        assert_that(items[0],
                    has_entry('Order', has_entry('Items', has_length(1))))
        assert_that(items[0],
                    has_entry('MimeType', 'application/vnd.nextthought.store.giftpurchaseattempt'))
        assert_that(items[0], has_entry('State', 'Success'))
        assert_that(items[0], has_entry('ChargeID', 'charge_1046'))
        assert_that(items[0], has_entry('TokenID', 'tok_1053'))
        assert_that(items[0], has_entry('ID', is_not(none())))
        assert_that(items[0], has_entry('NTIID', is_not(none())))
        assert_that(items[0], has_entry('Creator', is_('ichigo+@bleach.org')))
        assert_that(items[0], has_entry('SenderName', is_('Ichigo Kurosaki')))
        assert_that(items[0], has_entry('ReceiverName', is_('Aizen Sosuke')))
        assert_that(items[0], has_entry('DeliveryDate', is_not(none())))

        url = '/dataserver2/store/@@get_gift_purchase_attempt'
        params = {"purchaseID": items[0]['NTIID'],
                  'creator': 'ichigo+@bleach.org'}
        self.testapp.get(url, params=params, status=200)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.addAfterCommitHook')
    @fudge.patch('nti.store.payments.stripe.processor.purchase.create_charge')
    @fudge.patch('nti.store.payments.stripe.processor.purchase.get_transaction_runner')
    def test_gift_stripe_payment_preflight(self, mock_aach, mock_cc, mock_gtr):
        mock_aach.is_callable().with_args().calls(do_purchase)
        mock_gtr.is_callable().with_args().returns(MockRunner())

        self._create_fake_charge(199, mock_cc)

        # no purchasable
        url = '/dataserver2/store/@@gift_stripe_payment_preflight'
        params = {'purchasableId': None}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # invalid purchasable
        params = {'purchasableId': 'foo'}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # no token
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'token': None}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # invalid amount
        params = {'purchasableId': self.purchasable_id,
                  'amount': 'foo',
                  'token': "tok_1053"}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # no sender
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'token': "tok_1053",
                  "from": None}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # invalid from
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'token': "tok_1053",
                  "from": 'foo'}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # invalid receiver
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'from': 'ichigo@bleach.org',
                  'sender': 'Ichigo Kurosaki',
                  'receiver': 'aizen',
                  'token': "tok_1053",
                  'immediate': True}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # no receiver
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'from': 'ichigo@bleach.org',
                  'sender': 'Ichigo Kurosaki',
                  'token': "tok_1053",
                  'message': 'gift'}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        # no receiver
        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'from': 'ichigo@bleach.org',
                  'sender': 'Ichigo Kurosaki',
                  'token': "tok_1053",
                  'To': 'Aizen Sosuke'}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        params = {'purchasableId': self.purchasable_id,
                  'amount': 300,
                  'from': 'ichigo@bleach.org',
                  'sender': 'Ichigo Kurosaki',
                  'receiver': 'aizen@bleach.org',
                  'To': 'Aizen Sosuke',
                  'message': 'Getsuga Tenshou',
                  'token': "tok_1053",
                  'immediate': True}
        body = json.dumps(params)
        self.testapp.post(url, body, status=200)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_invalid_post_stripe_payment(self):
        url = '/dataserver2/store/@@post_stripe_payment'
        params = {'purchasableId': 'not found',
                  'amount': 300,
                  'token': 'xyz'}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

        params = {'purchasableId': self.purchasable_id,
                  'amount': 300}
        body = json.dumps(params)
        self.testapp.post(url, body, status=422)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_create_token(self):
        url = '/dataserver2/store/stripe/@@create_token'
        params = {
            'provider': 'CMU',
            'cvc': '019',
            'expiry': '0930',
            'number': '4012000033330026',
            'name': 'Ichigo Kurosaki',
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
                    has_entry('MimeType', 'application/vnd.nextthought.store.stripetoken'))
        assert_that(json_body,
                    has_entry('CardID', is_not(none())))
        assert_that(json_body,
                    has_entry('Type', 'Visa'))
        assert_that(json_body,
                    has_entry('Value', is_not(none())))
        assert_that(json_body,
                    has_entry('ID', is_not(none())))


_UNINITIALIZED = object()

class TestStripeConnectViews(ApplicationLayerTest):

    layer = ApplicationStoreTestLayer

    default_origin = 'http://mathcounts.nextthought.com'

    def _query_params(self, url):
        url_parts = list(urllib_parse.urlparse(url))
        # Query params are in index 4
        return OrderedDict(urllib_parse.parse_qsl(url_parts[4]))

    def _test_connect_stripe_account(self,
                                     mock_open,
                                     expected_dest_params,
                                     code="AUTH_CODE_298",
                                     state_for_redirect=_UNINITIALIZED,
                                     error=None,
                                     error_description=None,
                                     verify_empty_on_fail=True):

        with mock_dataserver.mock_db_trans():
            self._assign_role(ROLE_SITE_ADMIN, username='sjohnson@nextthought.com')

        class MockResponse(object):

            def __init__(self, code):
                self.code = code

            def getcode(self):
                return self.code

            def read(self):
                return json.dumps({
                    "token_type": "bearer",
                    "stripe_publishable_key": "PUB_KEY_111",
                    "scope": "read_write",
                    "livemode": False,
                    "stripe_user_id": "ACCOUNT_ABC",
                    "refresh_token": "REFRESH_TOKEN_222",
                    "access_token": "ACCESS_TOKEN_333"
                })

        mock_open.is_callable().returns(MockResponse(200))

        url = '/dataserver2/store/stripe/keys/@@stripe_connect_oauth1'
        res = self.testapp.get(url,
                               status=303,
                               extra_environ={
                                   b'HTTP_ORIGIN': b'http://mathcounts.nextthought.com'
                               })
        params = self._query_params(res.headers['LOCATION'])

        url = '/dataserver2/store/stripe/keys/@@stripe_connect_oauth2'
        body = {
            'scope': 'read_write',
        }

        if state_for_redirect is _UNINITIALIZED:
            body['state'] = params['state']
        elif state_for_redirect is None:
            pass
        else:
            body['state'] = state_for_redirect

        for key, val in (('code', code),
                         ('error', error),
                         ('error_description', error_description)):
            if val:
                body[key] = val

        res = self.testapp.get(url,
                               body,
                               status=303,
                               extra_environ={
                                   b'HTTP_ORIGIN': b'http://mathcounts.nextthought.com'
                               })

        location = res.headers['LOCATION']
        assert_that(location, starts_with('http://localhost/stripe_connect'))

        loc_params = self._query_params(location)
        assert_that(loc_params, has_entries(expected_dest_params))

        with mock_dataserver.mock_db_trans(site_name='mathcounts.nextthought.com'):
            key_container = get_stripe_key_container(create=False)
            if 'success' in loc_params:
                assert_that(key_container, not_(none()))
                assert_that(key_container, has_length(1))
                assert_that(key_container['default'], has_properties({
                    "Alias": "default",
                    "TokenType":  "bearer",
                    "PublicKey": "PUB_KEY_111",
                    "LiveMode": False,
                    "StripeUserID": "ACCOUNT_ABC",
                    "RefreshToken": "REFRESH_TOKEN_222",
                    "PrivateKey": "ACCESS_TOKEN_333"
                }))
            elif verify_empty_on_fail:
                assert_that(key_container, is_(none()))


    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.urllib2.urlopen')
    def test_connect_stripe_account_success(self, mock_open):
        self._test_connect_stripe_account(mock_open,
                                          {"success": "true"})

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.urllib2.urlopen')
    def test_connect_stripe_account_no_params(self, mock_open):
        self._test_connect_stripe_account(mock_open,
                                          {
                                              "error": "Invalid Request",
                                              "error_description": "Missing parameter: code"
                                          },
                                          code=None)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.urllib2.urlopen')
    def test_connect_stripe_account_no_state(self, mock_open):
        self._test_connect_stripe_account(mock_open,
                                          {
                                              "error": "Invalid Request",
                                              "error_description": "Missing parameter: state"
                                          },
                                          state_for_redirect=None)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.urllib2.urlopen')
    def test_connect_stripe_account_invalid_state(self, mock_open):
        self._test_connect_stripe_account(mock_open,
                                          {
                                              "error": "Server Error",
                                              "error_description": starts_with("Error Reference: "),
                                          },
                                          state_for_redirect='invalid')



    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.urllib2.urlopen')
    def test_connect_stripe_account_stripe_error(self, mock_open):
        self._test_connect_stripe_account(mock_open,
                                          {
                                              "error": "stripe error abc",
                                              "error_description": "user declined auth"
                                          },
                                          error="stripe error abc",
                                          error_description="user declined auth")

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_connect_stripe_account_site_admins_only(self):
        self.testapp.get('/dataserver2/store/stripe/keys/@@stripe_connect_oauth2',
                           None,
                           status=403)

    def _add_default_stripe_key(self):
        key_container = get_stripe_key_container()
        connect_key = PersistentStripeConnectKey(
            Alias=DEFAULT_STRIPE_KEY_ALIAS,
            StripeUserID=u"user_id_1",
            LiveMode=False,
            PrivateKey=u"private_key_1",
            RefreshToken=u"refresh_token_1",
            PublicKey=u"public_key_1",
            TokenType=u"bearer"
        )
        key_container.add_key(connect_key)

    def _assign_role_for_site(self, role, username, site=None):
        role_manager = IPrincipalRoleManager(site or getSite())
        role_name = getattr(role, "id", role)
        role_manager.assignRoleToPrincipal(role_name, username)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.urllib2.urlopen')
    @fudge.patch('nti.app.store.views.stripe_views.requests.post')
    def test_disconnect_stripe_account_success(self, mock_open, requests_post):
        self._test_connect_stripe_account(mock_open,
                                          {"success": "true"})
        with mock_dataserver.mock_db_trans(site_name='mathcounts.nextthought.com'):
            self._assign_role(ROLE_SITE_ADMIN, username='sjohnson@nextthought.com')

        def post(url, data=None, timeout=None, auth=None):
            return fudge.Fake().expects('raise_for_status').returns(None)

        requests_post.is_callable().calls(post)
        url = "/dataserver2/++etc++hostsites/mathcounts.nextthought.com/++etc++site/StripeConnectKeys/default"
        self.testapp.delete(url, status=204)
        self.testapp.delete(url, status=404)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_disconnect_stripe_account_site_admins_only(self):
        with mock_dataserver.mock_db_trans(site_name='mathcounts.nextthought.com'):
            self._add_default_stripe_key()

        url = "/dataserver2/++etc++hostsites/mathcounts.nextthought.com/++etc++site/StripeConnectKeys/default"
        self.testapp.delete(url, status=403)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_disconnect_stripe_account_not_connected(self):
        with mock_dataserver.mock_db_trans(site_name='mathcounts.nextthought.com'):
            self._assign_role(ROLE_SITE_ADMIN, username='sjohnson@nextthought.com')

        url = "/dataserver2/++etc++hostsites/mathcounts.nextthought.com/++etc++site/StripeConnectKeys/default"
        self.testapp.delete(url, status=404)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_stripe_connect_authorize_success(self):
        with mock_dataserver.mock_db_trans():
            self._assign_role(ROLE_SITE_ADMIN, username='sjohnson@nextthought.com')

        url = '/dataserver2/store/stripe/keys/@@stripe_connect_oauth1'
        res = self.testapp.get(url,
                               status=303,
                               extra_environ={
                                   b'HTTP_ORIGIN': b'http://mathcounts.nextthought.com'
                               })

        params = self._query_params(res.headers['LOCATION'])
        assert_that(params, has_entries({
            "client_id": "ca_1FSb6y5t7qj6DPOCQjEApTbc5Ou6XCHx",
            "response_type": "code",
            "scope": "read_write",
            "state": not_none(),
            "stripe_landing": "login",
        }))
        assert_that(params, not_(has_key("redirect_uri")))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.store.views.stripe_views.urllib2.urlopen')
    def test_stripe_connect_authorize_already_linked(self, mock_open):
        # Ensure one has already been linked
        self._test_connect_stripe_account(mock_open,
                                          {"success": "true"})

        with mock_dataserver.mock_db_trans():
            self._assign_role(ROLE_SITE_ADMIN, username='sjohnson@nextthought.com')

        url = '/dataserver2/store/stripe/keys/@@stripe_connect_oauth1'
        res = self.testapp.get(url,
                               status=303,
                               extra_environ={
                                   b'HTTP_ORIGIN': b'http://mathcounts.nextthought.com'
                               })

        # Attempt to link another should result in an error describing that.
        params = self._query_params(res.headers['LOCATION'])
        error_desc = "Another account has already been linked for this site."
        assert_that(params, has_entries({
            "error": "Already Linked",
            "error_description": error_desc
        }))
