#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

import zope.intid
from zope import component
from zope.event import notify

import transaction

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.dataserver import authorization as nauth

from nti.externalization import integer_strings
from nti.externalization.interfaces import LocatedExternalDict

from nti.ntiids.ntiids import is_valid_ntiid_string
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.store import NTIStoreException
from nti.store import InvalidPurchasable
from nti.store.purchasable import get_purchasable
from nti.store.invitations import get_purchase_by_code
from nti.store.purchase_history import get_purchase_attempt
from nti.store.purchase_attempt import create_purchase_attempt
from nti.store.purchase_history import get_pending_purchase_for
from nti.store.purchase_history import register_purchase_attempt

from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import PurchaseAttemptSuccessful

from nti.store.payments.stripe import STRIPE
from nti.store.payments.stripe import NoSuchStripeCoupon
from nti.store.payments.stripe import InvalidStripeCoupon
from nti.store.payments.stripe.interfaces import IStripeConnectKey
from nti.store.payments.stripe.stripe_purchase import create_stripe_priceable
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_item
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_order

from nti.utils.maps import CaseInsensitiveDict

from .._utils import safestr
from .._utils import to_boolean
from .._utils import is_valid_amount
from .._utils import is_valid_pve_int
from .._utils import is_valid_boolean
from .._utils import AbstractPostView

from .. import get_possible_site_names

from . import StorePathAdapter

_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=StorePathAdapter,
					  request_method='GET')
_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

_admin_view_defaults = _post_view_defaults.copy()
_admin_view_defaults['permission'] = nauth.ACT_MODERATE

# get views

class _BaseStripeView(object):

	processor = STRIPE

	def __init__(self, request):
		self.request = request

	def get_stripe_connect_key(self, params=None):
		params = CaseInsensitiveDict(params if params else self.request.params)
		keyname = params.get('provider')
		result = component.queryUtility(IStripeConnectKey, keyname)
		return result

@view_config(name="get_stripe_connect_key", **_view_defaults)
class GetStripeConnectKeyView(_BaseStripeView):

	def __call__(self):
		result = self.get_stripe_connect_key()
		if result is None:
			raise hexc.HTTPNotFound(detail=_('Provider not found'))
		return result

# post views

class _PostStripeView(_BaseStripeView, AbstractPostView):
	pass

@view_config(name="create_stripe_token", **_post_view_defaults)
class CreateStripeTokenView(_PostStripeView):

	def __call__(self):
		values = self.readInput()
		__traceback_info__ = values, self.request.params
		
		stripe_key = self.get_stripe_connect_key(values)
		manager = component.getUtility(IPaymentProcessor, name=self.processor)
		
		params = {'api_key':stripe_key.PrivateKey}
		customer_id = values.get('customerID') or values.get('customer_id')
		if not customer_id:
			required = (('cvc', 'cvc', ''),
						('exp_year', 'expYear', 'exp_year'),
						('exp_month', 'expMonth', 'exp_month'),
						('number', 'CC', 'number'))

			for k, p, a in required:
				value = values.get(p) or values.get(a)
				if not value:
					raise hexc.HTTPBadRequest(detail='Invalid %s value' % p)
				params[k] = safestr(value)
		else:
			params['customer_id'] = customer_id

		# optional
		optional = (('address_line1', 'address_line1', 'address'),
					('address_line2', 'address_line2', ''),
					('address_city', 'address_city', 'city'),
					('address_state', 'address_state', 'state'),
					('address_zip', 'address_zip', 'zip'),
					('address_country', 'address_country', 'country'))
		for k, p, a in optional:
			value = values.get(p) or values.get(a)
			if value:
				params[k] = safestr(value)

		token = manager.create_token(**params)
		return LocatedExternalDict(Token=token.id)

@view_config(name="price_purchasable_with_stripe_coupon", **_post_view_defaults)
class PricePurchasableWithStripeCouponView(_PostStripeView):

	def price(self, purchasable_id, quantity=None, coupon=None):
		pricer = component.getUtility(IPurchasablePricer, name=self.processor)
		priceable = create_stripe_priceable(ntiid=purchasable_id,
											quantity=quantity,
											coupon=coupon)
		result = pricer.price(priceable)
		return result

	def price_purchasable(self, values=None):
		values = values or self.readInput()
		coupon = values.get('coupon') or values.get('couponCode')
		purchasable_id = values.get('purchasableID') or values.get('purchasable_id')

		# check quantity
		quantity = values.get('quantity', 1)
		if not is_valid_pve_int(quantity):
			raise hexc.HTTPUnprocessableEntity(_("Invalid quantity"))
		quantity = int(quantity)

		try:
			result = self.price(purchasable_id, quantity, coupon)
			return result
		except NoSuchStripeCoupon:
			raise hexc.HTTPUnprocessableEntity(_("Cannot find stripe coupon"))
		except InvalidStripeCoupon:
			raise hexc.HTTPUnprocessableEntity(_("Invalid stripe coupon"))
		except InvalidPurchasable:
			raise hexc.HTTPUnprocessableEntity(_("Invalid purchasable"))

	def __call__(self):
		result = self.price_purchasable()
		return result

@view_config(name="post_stripe_payment", **_post_view_defaults)
class ProcessPaymentWithStripeView(_PostStripeView):

	def processInput(self, username):
		values = self.readInput()
		purchasable_id = values.get('purchasableID') or values.get('purchasable_id')
		if not purchasable_id:
			raise hexc.HTTPUnprocessableEntity(_("No item to purchase specified"))

		stripe_key = None
		purchasable = get_purchasable(purchasable_id)
		if purchasable is None:
			raise hexc.HTTPUnprocessableEntity(_("Invalid purchasable item"))
		else:
			provider = purchasable.Provider
			stripe_key = component.queryUtility(IStripeConnectKey, provider)
			if not stripe_key:
				raise hexc.HTTPUnprocessableEntity(_("Invalid purchasable provider"))

		token = values.get('token', None)
		if not token:
			raise hexc.HTTPUnprocessableEntity(_("No token provided"))

		expected_amount = values.get('amount', values.get('expectedAmount', None))
		if expected_amount is not None and not is_valid_amount(expected_amount):
			raise hexc.HTTPUnprocessableEntity(_("Invalid expected amount"))
		expected_amount = float(expected_amount) if expected_amount is not None else None

		coupon = values.get('coupon', None)
		description = values.get('description', None)

		quantity = values.get('quantity', None)
		if quantity is not None and not is_valid_pve_int(quantity):
			raise hexc.HTTPUnprocessableEntity(_("Invalid quantity"))
		quantity = int(quantity) if quantity else None

		description = description or "%s's payment for '%r'" % (username, purchasable_id)

		item = create_stripe_purchase_item(purchasable_id)
		po = create_stripe_purchase_order(item, quantity=quantity, coupon=coupon)

		pa = create_purchase_attempt(po, processor=self.processor)
		return pa, token, stripe_key, expected_amount

	def __call__(self):
		request = self.request

		username = request.authenticated_userid
		purchase_attempt, token, stripe_key, expected_amount = self.processInput(username)

		# check for any pending purchase for the items being bought
		purchase = get_pending_purchase_for(username, purchase_attempt.Items)
		if purchase is not None:
			logger.warn("There is already a pending purchase for item(s) %s",
						list(purchase_attempt.Items))
			return LocatedExternalDict({'Items':[purchase],
										'Last Modified':purchase.lastModified})

		# register purchase
		purchase_id = register_purchase_attempt(purchase_attempt, username)
		logger.info("Purchase attempt (%s) created", purchase_id)

		# after commit
		manager = component.getUtility(IPaymentProcessor, name=self.processor)
		site_names = get_possible_site_names(request, include_default=True)
		def process_purchase():
			logger.info("Processing purchase %s", purchase_id)
			manager.process_purchase(purchase_id=purchase_id, username=username,
									 token=token, expected_amount=expected_amount,
									 api_key=stripe_key.PrivateKey,
									 request=request,
									 site_names=site_names)

		transaction.get().addAfterCommitHook(
							lambda s: s and request.nti_gevent_spawn(process_purchase))

		# return
		purchase = get_purchase_attempt(purchase_id, username)
		return LocatedExternalDict({'Items':[purchase],
									'Last Modified':purchase.lastModified})

@view_config(name="generate_purchase_invoice_with_stripe", **_post_view_defaults)
class GeneratePurchaseInvoiceWitStripeView(_PostStripeView):

	def _get_purchase(self, key):
		try:
			integer_strings.from_external_string(key)
			purchase = get_purchase_by_code(key)
		except ValueError:
			if is_valid_ntiid_string(key):
				purchase = find_object_with_ntiid(key)
			else:
				purchase = None
		return purchase

	def __call__(self):
		values = self.readInput()
		transaction = values.get('transaction') or \
					  values.get('purchaseId') or \
                      values.get('code')
		if not transaction:
			msg = _("Must specified a valid transaction or purchase code")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = self._get_purchase(transaction)
		if purchase is None or not IPurchaseAttempt.providedBy(purchase):
			raise hexc.HTTPNotFound(detail=_('Transaction not found'))
		elif not purchase.has_succeeded():
			raise hexc.HTTPUnprocessableEntity(detail=_('Purchase was not successful'))

		manager = component.getUtility(IPaymentProcessor, name=self.processor)
		payment_charge = manager.get_payment_charge(purchase)

		notify(PurchaseAttemptSuccessful(purchase, payment_charge, request=self.request))
		return hexc.HTTPNoContent()

# admin views

@view_config(name="refund_payment_with_stripe", **_admin_view_defaults)
class RefundPaymentWithStripeView(_PostStripeView):

	def processInput(self):
		values = self.readInput()
		trax_id = values.get('transactionId', values.get('transaction_id', None))
		if not trax_id:
			raise hexc.HTTPUnprocessableEntity(_("No transaction id specified"))

		amount = values.get('amount', None)
		if amount is not None and not is_valid_amount(amount):
			raise hexc.HTTPUnprocessableEntity(_("Invalid amount"))
		amount = float(amount) if amount is not None else None

		refund_application_fee = values.get('refundApplicationFee') or \
								 values.get('refund_application_fee')

		if refund_application_fee is not None:
			if not is_valid_boolean(refund_application_fee):
				raise hexc.HTTPUnprocessableEntity(_("Invalid refund application fee"))
			refund_application_fee = to_boolean(refund_application_fee)

	def __call__(self):
		request = self.request
		trx_id, amount, refund_application_fee = self.processInput()
		manager = component.getUtility(IPaymentProcessor, name=self.processor)
		try:
			manager.refund_purchase(trx_id, amount=amount,
									refund_application_fee=refund_application_fee,
									request=request)
		except NTIStoreException:
			logger.exception("Error while refunding transaction")
			msg = _("Error while refunding transaction")
			raise hexc.HTTPUnprocessableEntity(msg)

		# return
		uid = integer_strings.from_external_string(trx_id)
		zope_iids = component.getUtility(zope.intid.IIntIds)
		purchase = zope_iids.queryObject(uid)

		result = LocatedExternalDict({'Items':[purchase],
									  'Last Modified':purchase.lastModified})
		return result

del _view_defaults
del _post_view_defaults
del _admin_view_defaults
