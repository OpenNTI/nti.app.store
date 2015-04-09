#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

import six
import sys
from datetime import date
from datetime import datetime
from functools import partial

from zope import component
from zope.event import notify

import transaction

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error as raise_error
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.common.string import safestr
from nti.common.maps import CaseInsensitiveDict

from nti.dataserver import authorization as nauth
from nti.dataserver.users.interfaces import checkEmailAddress

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.externalization import to_external_object
from nti.externalization.internalization import update_from_external_object

from nti.store import PricingException
from nti.store import InvalidPurchasable

from nti.store.store import get_purchasable
from nti.store.store import get_purchase_attempt
from nti.store.store import get_purchase_by_code
from nti.store.store import get_pending_purchases
from nti.store.store import create_purchase_attempt
from nti.store.store import register_purchase_attempt
from nti.store.store import get_gift_pending_purchases
from nti.store.store import create_gift_purchase_attempt
from nti.store.store import register_gift_purchase_attempt

from nti.store.interfaces import IPricingError
from nti.store.interfaces import IPaymentProcessor
from nti.store.interfaces import IPurchasablePricer
from nti.store.interfaces import IPurchasableChoiceBundle
from nti.store.interfaces import PurchaseAttemptSuccessful

from nti.store.payments.stripe import STRIPE
from nti.store.payments.stripe import NoSuchStripeCoupon
from nti.store.payments.stripe import InvalidStripeCoupon
from nti.store.payments.stripe.utils import replace_items_coupon
from nti.store.payments.stripe.interfaces import IStripeConnectKey
from nti.store.payments.stripe.interfaces import IStripePurchaseOrder
from nti.store.payments.stripe.stripe_purchase import create_stripe_priceable
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_item
from nti.store.payments.stripe.stripe_purchase import create_stripe_purchase_order

from ..utils import is_true
from ..utils import to_boolean
from ..utils import is_valid_amount
from ..utils import is_valid_pve_int
from ..utils import is_valid_boolean
from ..utils import AbstractPostView

from .. import get_possible_site_names

from . import StorePathAdapter

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED

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

			for key, param, alias in required:
				value = values.get(param) or values.get(alias)
				if not value:
					raise_error(self.request,
								hexc.HTTPUnprocessableEntity,
								{	'message': _("Invalid value."),
									'field': param },
								None)
				params[key] = safestr(value)
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

def price_order(order, processor=STRIPE):
	pricer = component.getUtility(IPurchasablePricer, name=processor)
	result = pricer.evaluate(order)
	return result

def _call_pricing_func(func):
	try:
		result = func()
	except NoSuchStripeCoupon:
		result = IPricingError(_("Invalid coupon"))
	except InvalidStripeCoupon:
		result = IPricingError(_("Invalid coupon"))
	except InvalidPurchasable:
		result = IPricingError(_("Invalid purchasable"))
	except PricingException as e:
		result = IPricingError(e)
	except Exception:
		raise
	return result

@view_config(name="price_stripe_order", **_noauth_post_view_defaults)
class PriceStripeOrderView(AbstractAuthenticatedView,
						   ModeledContentUploadRequestUtilsMixin):
	
	content_predicate = IStripePurchaseOrder.providedBy

	def readCreateUpdateContentObject(self, *args, **kwargs):
		externalValue = self.readInput()
		result = find_factory_for(externalValue)()
		update_from_external_object(result, externalValue)
		return result
		
	def _do_call(self):
		order = self.readCreateUpdateContentObject()
		assert IStripePurchaseOrder.providedBy(order)
		if order.Coupon: # replace item coupons
			replace_items_coupon(order, None)

		result = _call_pricing_func(partial(price_order, order))
		status = 422 if IPricingError.providedBy(result) else 200
		self.request.response.status_int = status
		return result
	
@view_config(name="price_purchasable_with_stripe_coupon", **_noauth_post_view_defaults)
class PricePurchasableWithStripeCouponView(_PostStripeView):

	def price_purchasable(self, values=None):
		values = values or self.readInput()
		coupon = values.get('coupon') or values.get('couponCode')
		purchasable_id = values.get('purchasable') or \
						 values.get('purchasableId') or \
						 values.get('purchasable_Id') or u''

		# check quantity
		quantity = values.get('quantity', 1)
		if not is_valid_pve_int(quantity):
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Invalid quantity."),
							'field': 'quantity' },
						None)
		quantity = int(quantity)

		pricing_func = partial(perform_pricing, 
					  		   purchasable_id=purchasable_id,
					   		   quantity=quantity, 
					   		   coupon=coupon)
		result = _call_pricing_func(pricing_func)
		status = 422 if IPricingError.providedBy(result) else 200
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

	def parseContext(self, values, purchasables=()):
		context = dict()
		for purchasable in purchasables:
			vendor = to_external_object(purchasable.VendorInfo) \
					 if purchasable.VendorInfo else None
			context.update(vendor or {})
			
		# capture user context data
		data = CaseInsensitiveDict(values.get('Context') or {})
		for name, alias, klass in self.KEYS:
			value = data.get(name)
			value = data.get(alias) if value is None else value
			if value is not None:
				context[name] = klass(value)
		return context

	def validatePurchasable(self, request, purchasable_id):
		purchasable = get_purchasable(purchasable_id)
		if purchasable is None:
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a valid purchasable."),
							'field' : 'purchasables',
							'value': purchasable_id },
						None)
		return purchasable

	def validatePurchasables(self, request, values, purchasables=()):
		result = [self.validatePurchasable(request, p) for p in purchasables]
		return result

	def validateStripeKey(self, request, purchasables=()):
		result = None
		for purchasable in purchasables:
			provider = purchasable.Provider
			stripe_key = component.queryUtility(IStripeConnectKey, provider)
			if stripe_key is None:
				raise_error(request,
							hexc.HTTPUnprocessableEntity,
							{	'message': _("Invalid purchasable provider."),
								'field': 'purchasables',
								'value': provider },
							None)
			if result is None:
				result = stripe_key
			elif result !=  stripe_key:
				raise_error(request,
							hexc.HTTPUnprocessableEntity,
							{	'message': _("Cannot mix purchasable providers."),
								'field': 'purchasables' },
							None)
		return result
	
	def getPaymentRecord(self, request, values=None):
		values = values or self.readInput()
		result = CaseInsensitiveDict()
		purchasables = 	values.get('purchasableId') or \
						values.get('purchasable') or \
						values.get('purchasables')
		if not purchasables:
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a purchasable."),
							'field': 'purchasables' },
						None)
		elif isinstance(purchasables, six.string_types):
			purchasables = list(set(purchasables.split())) 
		result['Purchasables'] = purchasables

		purchasables = self.validatePurchasables(request, values, purchasables)
		stripe_key = self.validateStripeKey(request, purchasables)
		result['StripeKey'] = stripe_key

		context = self.parseContext(values, purchasables)
		result['Context'] = context

		token = values.get('token', None)
		if not token:
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a valid stripe token."),
							'field': 'token' },
						None)
			raise hexc.HTTPUnprocessableEntity(_("No token provided"))
		result['Token'] = token

		expected_amount = values.get('amount') or values.get('expectedAmount')
		if expected_amount is not None and not is_valid_amount(expected_amount):
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Invalid expected amount."),
							'field': 'amount' },
						None)
		expected_amount = float(expected_amount) if expected_amount is not None else None
		result['Amount'] = result['ExpectedAmount'] = expected_amount

		coupon = values.get('coupon', None)
		result['Coupon'] = coupon

		quantity = values.get('quantity', None)
		if quantity is not None and not is_valid_pve_int(quantity):
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Invalid quantity."),
							'field': 'quantity' },
						None)
		quantity = int(quantity) if quantity else None
		result['Quantity'] = quantity

		description = values.get('description', None)
		result['Description'] = description
		return result

	def validateCoupon(self, request, record):
		coupon = record['Coupon']
		if coupon:
			manager = component.getUtility(IPaymentProcessor, name=self.processor)
			try:
				if not manager.validate_coupon(coupon):
					raise_error(request,
								hexc.HTTPUnprocessableEntity,
								{	'message': _("Invalid coupon."),
									'field': 'coupon'},
								None)
			except StandardError as e:
				exc_info = sys.exc_info()
				raise_error(request,
							hexc.HTTPUnprocessableEntity,
							{	'message': _("Invalid coupon."),
								'field': 'coupon',
								'code': e.__class__.__name__},
							exc_info[2])
		return record
	
	def createPurchaseOrder(self, record):
		items = [create_stripe_purchase_item(p) for p in record['Purchasables']]
		result = create_stripe_purchase_order(tuple(items),
											  quantity=record['Quantity'],
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
		return LocatedExternalDict({ITEMS:[purchase_attempt],
									LAST_MODIFIED:purchase_attempt.lastModified})
	def __call__(self):
		values = self.readInput()
		record = self.getPaymentRecord(self.request, values)
		purchase_attempt = self.createPurchaseAttempt(record)
		result = self.processPurchase(purchase_attempt, record)
		return result

@view_config(name="post_stripe_payment", **_post_view_defaults)
class ProcessPaymentWithStripeView(AbstractAuthenticatedView, BasePaymentWithStripeView):

	def validatePurchasable(self, request, purchasable_id):
		purchasable = super(ProcessPaymentWithStripeView, self).validatePurchasable(request, purchasable_id)
		if IPurchasableChoiceBundle.providedBy(purchasable):
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Cannot purchase a bundle item."),
							'field' : 'purchasables',
							'value': purchasable_id },
						None)
		return purchasable
	
	@property
	def username(self):
		return self.remoteUser.username

	def registerPurchaseAttempt(self, purchase_attempt, record):
		purchase_id = register_purchase_attempt(purchase_attempt, self.username)
		return purchase_id

	def __call__(self):
		username = self.username
		values = self.readInput()
		record = self.getPaymentRecord(self.request, values)
		purchase_attempt = self.createPurchaseAttempt(record)

		# check for any pending purchase for the items being bought
		purchases = get_pending_purchases(username, purchase_attempt.Items)
		if purchases:
			lastModified = max(map(lambda x: x.lastModified, purchases)) or 0
			logger.warn("There are pending purchase(s) for item(s) %s",
						list(purchase_attempt.Items))
			return LocatedExternalDict({ITEMS: purchases,
										LAST_MODIFIED: lastModified})

		result = self.processPurchase(purchase_attempt, record)
		return result

@view_config(name="gift_stripe_payment_preflight", **_noauth_post_view_defaults)
class GiftWithStripePreflightView(AbstractAuthenticatedView, BasePaymentWithStripeView):

	def readInput(self, value=None):
		values = super(GiftWithStripePreflightView, self).readInput(value=value)
		values.pop('Quantity', None) # ignore quantity
		return values

	def getPaymentRecord(self, request, values):
		record = super(GiftWithStripePreflightView, self).getPaymentRecord(request, values)
		creator = values.get('from') or values.get('sender') or values.get('creator')
		if not creator:
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a sender email."),
							'field': 'from' },
						None)

		try:
			checkEmailAddress(creator)
		except Exception as e:
			exc_info = sys.exc_info()
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a valid sender email."),
							'field': 'from',
							'code': e.__class__.__name__ },
						exc_info[2])
		record['From'] = record['Creator'] = creator

		record['SenderName'] = record['Sender'] = \
				values.get('senderName') or values.get('sender') or values.get('from')

		receiver = values.get('receiver')
		if receiver:
			try:
				checkEmailAddress(receiver)
			except Exception as e:
				exc_info = sys.exc_info()
				raise_error(request,
							hexc.HTTPUnprocessableEntity,
							{	'message': _("Please provide a valid receiver email."),
								'field': 'receiver',
								'code': e.__class__.__name__ },
							exc_info[2])
		record['Receiver'] = receiver
		receiverName = record['To'] = record['ReceiverName'] =  \
				values.get('to') or values.get('receiverName') or values.get('receiver')

		immediate = values.get('immediate') or values.get('deliverNow')
		if is_true(immediate):
			if not receiver:
				raise_error(request,
							hexc.HTTPUnprocessableEntity,
							{	'message': _("Please provide a receiver email."),
								'field': 'immediate' },
							None)
			today = date.today()
			now = datetime(year=today.year, month=today.month, day=today.day)
			record['DeliveryDate'] = now
		else:
			record['DeliveryDate'] = None
		record['Immediate'] = bool(immediate)
			
		message = record['Message'] = values.get('message')
		if (message or receiverName) and not receiver:
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a receiver email."),
							'field': 'message' },
						None)
		return record

	@property
	def username(self):
		return None

	def createPurchaseAttempt(self, record):
		pass
	
	def registerPurchaseAttempt(self, purchase_attempt, record):
		pass
	
	def __call__(self):
		values = self.readInput()
		request = self.request
		record = self.getPaymentRecord(request, values)
		self.validateCoupon(request, record)
		return record
	
@view_config(name="gift_stripe_payment", **_noauth_post_view_defaults)
class GiftWithStripeView(GiftWithStripePreflightView):

	def createPurchaseAttempt(self, record):
		order = self.createPurchaseOrder(record)
		result = create_gift_purchase_attempt(order=order,
											  processor=self.processor,
											  sender=record['Sender'],
											  creator=record['Creator'],
											  message=record['Message'],
										 	  context=record['Context'],
										 	  receiver=record['Receiver'],
										 	  receiver_name=record['ReceiverName'],
										 	  delivery_date=record['DeliveryDate'])
		return result

	def registerPurchaseAttempt(self, purchase, record):
		result = register_gift_purchase_attempt(record['Creator'], purchase)
		return result

	def __call__(self):
		values = self.readInput()
		record = self.getPaymentRecord(self.request, values)
		purchase_attempt = self.createPurchaseAttempt(record)

		# check for any pending gift purchase
		creator = record['Creator']
		purchases = get_gift_pending_purchases(creator)
		if purchases:
			lastModified = max(map(lambda x: x.lastModified, purchases)) or 0
			logger.warn("There are pending purchase(s) for item(s) %s",
						list(purchase_attempt.Items))
			return LocatedExternalDict({ITEMS: purchases,
										LAST_MODIFIED:lastModified})

		result = self.processPurchase(purchase_attempt, record)
		return result

def find_purchase(key):
	try:
		purchase = get_purchase_by_code(key)
	except ValueError:
		purchase = get_purchase_attempt(key)
	return purchase
	
@view_config(name="generate_purchase_invoice_with_stripe", **_post_view_defaults)
class GeneratePurchaseInvoiceWitStripeView(_PostStripeView):

	def __call__(self):
		values = self.readInput()
		trx_id = values.get('transactionId') or \
				 values.get('transaction') or \
				 values.get('purchaseId') or \
				 values.get('purchase') or \
                 values.get('code')
		if not trx_id:
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a transaction id."),
							'field': 'transaction' },
						None)

		purchase = find_purchase(trx_id)
		if purchase is None:
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Transaction not found."),
							'field': 'transaction' },
						None)
		elif not purchase.has_succeeded():
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Transaction was not successful."),
							'field': 'transaction' },
						None)
		manager = component.getUtility(IPaymentProcessor, name=self.processor)
		payment_charge = manager.get_payment_charge(purchase)

		notify(PurchaseAttemptSuccessful(purchase, payment_charge, request=self.request))
		return hexc.HTTPNoContent()

def refund_purchase(purchase, amount, refund_application_fee, request, processor=STRIPE):
	manager = component.getUtility(IPaymentProcessor, name=processor)
	return manager.refund_purchase(	purchase, amount=amount,
									refund_application_fee=refund_application_fee,
									request=request)

@view_config(name="refund_payment_with_stripe", **_admin_view_defaults)
class RefundPaymentWithStripeView(_PostStripeView):

	def processInput(self):
		values = self.readInput()
		trx_id = values.get('transactionId') or \
				 values.get('transaction') or \
				 values.get('purchaseId') or \
				 values.get('purchase') or \
                 values.get('code')
		if not trx_id:
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a transaction id."),
							'field': 'transaction' },
						None)

		purchase = find_purchase(trx_id)
		if purchase is None:
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Transaction not found."),
							'field': 'transaction' },
						None)
		elif not purchase.has_succeeded():
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Transaction was not successful."),
							'field': 'transaction' },
						None)
			
		amount = values.get('amount', None)
		if amount is not None and not is_valid_amount(amount):
			raise_error(self.request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Please provide a valid amount."),
							'field': 'amount' },
						None)
		amount = float(amount) if amount is not None else None

		refund_application_fee = values.get('refundApplicationFee') or \
								 values.get('refund_application_fee')

		if refund_application_fee is not None:
			if not is_valid_boolean(refund_application_fee):
				raise_error(self.request,
							hexc.HTTPUnprocessableEntity,
							{	'message': _("Please provide a valid application fee."),
								'field': 'refundApplicationFee' },
							None)
			refund_application_fee = to_boolean(refund_application_fee)

		return purchase, amount, refund_application_fee

	def __call__(self):
		request = self.request
		purchase, amount, refund_application_fee = self.processInput()
		try:
			refund_purchase(purchase, amount=amount,
							refund_application_fee=refund_application_fee,
							request=request)
		except Exception as e:
			logger.exception("Error while refunding transaction")
			exc_info = sys.exc_info()
			raise_error(request,
						hexc.HTTPUnprocessableEntity,
						{	'message': _("Error while refunding transaction."),
							'code': e.__class__.__name__ },
						exc_info[2])

		result = LocatedExternalDict({ITEMS:[purchase],
									  LAST_MODIFIED:purchase.lastModified})
		return result

del _view_defaults
del _post_view_defaults
del _admin_view_defaults
del _noauth_post_view_defaults
