#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

from functools import partial

import zope.intid

from zope import component
from zope.event import notify

import transaction

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.dataserver import authorization as nauth
from nti.dataserver.users.interfaces import checkEmailAddress

from nti.externalization import integer_strings
from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.externalization import to_external_object

from nti.ntiids.ntiids import is_valid_ntiid_string
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.store import PricingException
from nti.store import InvalidPurchasable

from nti.store.store import get_purchasable
from nti.store.store import get_purchase_by_code
from nti.store.store import get_pending_purchases
from nti.store.store import create_purchase_attempt
from nti.store.store import register_purchase_attempt
from nti.store.store import get_gift_pending_purchases
from nti.store.store import create_gift_purchase_attempt
from nti.store.store import register_gift_purchase_attempt

from nti.store.interfaces import IPricingError
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

from ..utils import safestr
from ..utils import to_boolean
from ..utils import is_valid_amount
from ..utils import is_valid_pve_int
from ..utils import is_valid_boolean
from ..utils import AbstractPostView

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

_noauth_post_view_defaults = _post_view_defaults.copy()
_noauth_post_view_defaults.pop('permission', None)

class _BaseStripeView(AbstractAuthenticatedView):

	processor = STRIPE

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


def perform_pricing(purchasable_id, quantity=None, coupon=None, processor=STRIPE):
	pricer = component.getUtility(IPurchasablePricer, name=processor)
	priceable = create_stripe_priceable(ntiid=purchasable_id,
										quantity=quantity,
										coupon=coupon)
	result = pricer.price(priceable)
	return result

@view_config(name="price_purchasable_with_stripe_coupon", **_post_view_defaults)
class PricePurchasableWithStripeCouponView(_PostStripeView):

	def price(self, purchasable_id, quantity=None, coupon=None):
		result = perform_pricing(purchasable_id, quantity=quantity, coupon=coupon, 
								 processor=self.processor)
		return result

	def price_purchasable(self, values=None):
		result = None
		values = values or self.readInput()
		coupon = values.get('coupon') or values.get('couponCode')
		purchasable_id = values.get('purchasableID') or values.get('purchasable_id')

		# check quantity
		quantity = values.get('quantity', 1)
		if not is_valid_pve_int(quantity):
			raise hexc.HTTPUnprocessableEntity(_("Invalid quantity"))
		quantity = int(quantity)

		status = 422
		try:
			result = self.price(purchasable_id, quantity, coupon)
		except NoSuchStripeCoupon:
			result = IPricingError(_("Cannot find stripe coupon"))
		except InvalidStripeCoupon:
			result = IPricingError(_("Invalid stripe coupon"))
		except InvalidPurchasable:
			result = IPricingError(_("Invalid purchasable"))
		except PricingException as e:
			result = IPricingError(e)
		except StandardError:
			raise
		else:
			status = 200
			
		self.request.response.status_int = status
		return result

	def __call__(self):
		result = self.price_purchasable()
		return result

def process_purchase(manager, purchase_id, username, token, expected_amount,
					 stripe_key, request, site_names=()):
	logger.info("Processing purchase %s", purchase_id)
	manager.process_purchase(purchase_id=purchase_id, username=username,
							 token=token, expected_amount=expected_amount,
							 api_key=stripe_key.PrivateKey,
							 request=request,
							 site_names=site_names)

def addAfterCommitHook(manager, purchase_id, username, token, expected_amount,
					   stripe_key, request, site_names=()):
	
	processor = partial(process_purchase, 
						token=token,
						request=request,
						manager=manager,
						username=username,
						site_names=site_names,
						stripe_key=stripe_key,
						purchase_id=purchase_id,
						expected_amount=expected_amount)
	
	transaction.get().addAfterCommitHook(
					lambda s: s and request.nti_gevent_spawn(processor))

class BasePaymentWithStripeView(ModeledContentUploadRequestUtilsMixin):
		
	processor = STRIPE
	
	KEYS = (('AllowVendorUpdates', 'allow_vendor_updates', bool),)
	
	def readInput(self, value=None):
		result = super(BasePaymentWithStripeView,self).readInput(value=value)
		result = CaseInsensitiveDict(result or {})
		return result

	def parseContext(self, values, purchasable):
		# get purchasable vendor info
		context = to_external_object(purchasable.VendorInfo) \
				  if purchasable.VendorInfo else dict()

		# capture user context data
		data = CaseInsensitiveDict(values.get('Context') or {})
		for name, alias, klass in self.KEYS:
			value = data.get(name)
			value = data.get(alias) if value is None else value
			if value is not None:
				context[name] = klass(value)
		return context
			
	def getPaymentRecord(self, values=None):
		values = values or self.readInput()
		result = CaseInsensitiveDict()
		purchasable_id = values.get('purchasableID') or values.get('purchasable_id')
		if not purchasable_id:
			raise hexc.HTTPUnprocessableEntity(_("No item to purchase specified"))
		result['PurchasableID'] = purchasable_id
		
		stripe_key = None
		purchasable = get_purchasable(purchasable_id)
		if purchasable is None:
			raise hexc.HTTPUnprocessableEntity(_("Invalid purchasable item"))
		else:
			provider = purchasable.Provider
			stripe_key = component.queryUtility(IStripeConnectKey, provider)
			if not stripe_key:
				raise hexc.HTTPUnprocessableEntity(_("Invalid purchasable provider"))
		result['StripeKey'] = stripe_key

		context = self.parseContext(values, purchasable)
		result['Context'] = context
		
		token = values.get('token', None)
		if not token:
			raise hexc.HTTPUnprocessableEntity(_("No token provided"))
		result['Token'] = token
		
		expected_amount = values.get('amount') or values.get('expectedAmount')
		if expected_amount is not None and not is_valid_amount(expected_amount):
			raise hexc.HTTPUnprocessableEntity(_("Invalid expected amount"))
		expected_amount = float(expected_amount) if expected_amount is not None else None
		result['Amount'] = result['ExpectedAmount'] = expected_amount
		
		coupon = values.get('coupon', None)
		result['Coupon'] = coupon
		
		quantity = values.get('quantity', None)
		if quantity is not None and not is_valid_pve_int(quantity):
			raise hexc.HTTPUnprocessableEntity(_("Invalid quantity"))
		quantity = int(quantity) if quantity else None
		result['Quantity'] = quantity
		
		description = values.get('description', None)
		result['Description'] = description
		return result

	def createPurchaseOrder(self, record):
		item = create_stripe_purchase_item(record['PurchasableID'] )
		result = create_stripe_purchase_order(item, quantity=record['Quantity'],
											  coupon=record['coupon'])
		return result
	
	def createPurchaseAttempt(self, record):
		order = self.createPurchaseOrder(record)
		result = create_purchase_attempt(order, processor=self.processor, 
										 context=record['Context'])
		return result
	
	def registerPurchaseAttempt(self, purchase_attempt, record):
		raise NotImplementedError()
	
	@property
	def username(self):
		return None
	
	def processPurchase(self, purchase_attempt, record):
		purchase_id = self.registerPurchaseAttempt(purchase_attempt, record)
		logger.info("Purchase attempt (%s) created", purchase_id)
		
		token = record['Token']
		stripe_key = record['StripeKey']
		expected_amount = record['ExpectedAmount']
		
		request = self.request
		username = self.username
		site_names = get_possible_site_names(request, include_default=True)
		manager = component.getUtility(IPaymentProcessor, name=self.processor)
		
		# process purchase after commit
		addAfterCommitHook(	token=token,
						   	request=request,
							manager=manager,
							username=username,
							site_names=site_names,
							stripe_key=stripe_key,
							purchase_id=purchase_id,
							expected_amount=expected_amount)
	
		# return
		return LocatedExternalDict({'Items':[purchase_attempt],
									'Last Modified':purchase_attempt.lastModified})
	def __call__(self):
		values = self.readInput()
		record = self.getPaymentRecord(values)
		purchase_attempt = self.createPurchaseAttempt(record)
		result = self.processPurchase(purchase_attempt, record)
		return result

@view_config(name="post_stripe_payment", **_post_view_defaults)
class ProcessPaymentWithStripeView(AbstractAuthenticatedView, BasePaymentWithStripeView):

	def getPaymentRecord(self, values=None):
		record = super(ProcessPaymentWithStripeView, self).getPaymentRecord(values)
		purchasable_id = record['PurchasableID']
		description = record['Description']
		if not description:
			record['Description'] = "%s's payment for '%r'" % (self.username, purchasable_id)
		return record

	@property
	def username(self):
		return self.remoteUser.username
	
	def registerPurchaseAttempt(self, purchase_attempt, record):
		purchase_id = register_purchase_attempt(purchase_attempt, self.username)
		return purchase_id
	
	def __call__(self):
		username = self.username
		values = self.readInput()
		record = self.getPaymentRecord(values)
		purchase_attempt = self.createPurchaseAttempt(record)
		
		# check for any pending purchase for the items being bought
		purchases = get_pending_purchases(username, purchase_attempt.Items)
		if purchases:
			lastModified = max(map(lambda x: x.lastModified, purchases)) or 0
			logger.warn("There are pending purchase(s) for item(s) %s",
						list(purchase_attempt.Items))
			return LocatedExternalDict({'Items': purchases,
										'Last Modified':lastModified})
		
		result = self.processPurchase(purchase_attempt, record)
		return result

@view_config(name="gift_stripe_payment", **_noauth_post_view_defaults)
class GiftWithStripeView(AbstractAuthenticatedView, BasePaymentWithStripeView):

	def readInput(self):
		values = super(GiftWithStripeView, self).readInput()
		values.pop('Quantity', None) # ignore quantity	
		return values
	
	def getPaymentRecord(self, values):
		record = super(GiftWithStripeView, self).getPaymentRecord(values)
		creator = values.get('creator') or values.get('sender') or values.get('from')
		if not creator:
			raise hexc.HTTPUnprocessableEntity(_("Invalid sender"))
		try:
			checkEmailAddress(creator)
		except:
			raise hexc.HTTPUnprocessableEntity(_("Invalid sender email"))
		record['Creator'] = creator

		record['Message'] = values.get('message')
		record['Sender'] = values.get('sender') or values.get('from')
		receiver = values.get('receiver') or values.get('to')
		if receiver:
			try:
				checkEmailAddress(receiver)
			except:
				raise hexc.HTTPUnprocessableEntity(_("Invalid receiver email"))
		record['Receiver'] = receiver
		
		purchasable_id = record['PurchasableID']
		description = record['Description']
		if not description:
			record['Description'] = "payment for gift '%r'" % purchasable_id
		return record

	@property
	def username(self):
		return None
	
	def createPurchaseAttempt(self, record):
		order = self.createPurchaseOrder(record)
		result = create_gift_purchase_attempt(order=order, 
											  processor=self.processor,
											  sender=record['Sender'],
											  creator=record['Creator'],
											  message=record['Message'],
										 	  context=record['Context'],
										 	  receiver=record['Receiver'])
		return result

	def registerPurchaseAttempt(self, purchase, record):
		result = register_gift_purchase_attempt(record['Creator'], purchase)
		return result
	
	def __call__(self):
		values = self.readInput()
		record = self.getPaymentRecord(values)
		purchase_attempt = self.createPurchaseAttempt(record)
		
		# check for any pending gift purchase
		creator = record['Creator']
		purchases = get_gift_pending_purchases(creator)
		if purchases:
			lastModified = max(map(lambda x: x.lastModified, purchases)) or 0
			logger.warn("There are pending purchase(s) for item(s) %s",
						list(purchase_attempt.Items))
			return LocatedExternalDict({'Items': purchases,
										'Last Modified':lastModified})
		
		result = self.processPurchase(purchase_attempt, record)
		return result
	
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
		except StandardError:
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
del _noauth_post_view_defaults
