#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

from .. import MessageFactory as _

logger = __import__('logging').getLogger(__name__)

import six
import time
import gevent
import numbers
import dateutil.parser

from zope import component
from zope import interface
from zope.location.interfaces import IContained
from zope.container import contained as zcontained
from zope.traversing.interfaces import IPathAdapter

from pyramid.view import view_config
from pyramid import httpexceptions as hexc
from pyramid.authorization import ACLAuthorizationPolicy

from nti.appserver.dataserver_pyramid_views import _GenericGetView as GenericGetView

from nti.dataserver import authorization as nauth
from nti.dataserver import interfaces as nti_interfaces

from nti.externalization.interfaces import LocatedExternalDict

from nti.store import priceable
from nti.store import invitations
from nti.store import purchasable
from nti.store import purchase_history
from nti.store import InvalidPurchasable
from nti.store import interfaces as store_interfaces

from nti.utils.maps import CaseInsensitiveDict

from .. import STORE
from .._utils import AbstractPostView
from .._utils import is_valid_pve_int
from .._utils import is_valid_timestamp

@interface.implementer(IPathAdapter, IContained)
class StorePathAdapter(zcontained.Contained):

	__name__ = STORE

	def __init__(self, context, request):
		self.context = context
		self.request = request
		self.__parent__ = context

_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=StorePathAdapter,
					  request_method='GET')
_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

# get views

class _PurchaseAttemptView(object):

	def __init__(self, request):
		self.request = request

	def _last_modified(self, purchases):
		result = 0
		for pa in purchases or ():
			result = max(result, getattr(pa, "lastModified", 0))
		return result

@view_config(name="get_pending_purchases", **_view_defaults)
class GetPendingPurchasesView(_PurchaseAttemptView):

	def __call__(self):
		request = self.request
		username = request.authenticated_userid
		purchases = purchase_history.get_pending_purchases(username)
		result = LocatedExternalDict({'Items': purchases,
									  'Last Modified':self._last_modified(purchases)})
		return result

@view_config(name="get_purchase_history", **_view_defaults)
class GetPurchaseHistoryView(_PurchaseAttemptView):

	def _convert(self, t):
		result = t
		if is_valid_timestamp(t):
			result = float(t)
		elif isinstance(t, six.string_types):
			result = time.mktime(dateutil.parser(t).timetuple())
		return result if isinstance(t, numbers.Number) else None

	def __call__(self):
		request = self.request
		username = request.authenticated_userid
		purchasable_id = request.params.get('purchasableID', None)
		if not purchasable_id:
			start_time = self._convert(request.params.get('startTime', None))
			end_time = self._convert(request.params.get('endTime', None))
			purchases = purchase_history.get_purchase_history(username,
															  start_time, end_time)
		else:
			purchases = purchase_history.get_purchase_history_by_item(username,
																	  purchasable_id)
		result = LocatedExternalDict({'Items': purchases,
									  'Last Modified':self._last_modified(purchases)})
		return result

def _sync_purchase(purchase):
	purchase_id = purchase.id
	username = purchase.creator.username

	def sync_purchase():
		manager = component.getUtility(store_interfaces.IPaymentProcessor,
									   name=purchase.Processor)
		manager.sync_purchase(purchase_id=purchase_id, username=username)

	def process_sync():
		component.getUtility(nti_interfaces.IDataserverTransactionRunner)(sync_purchase)

	gevent.spawn(process_sync)

@view_config(name="get_purchase_attempt", **_view_defaults)
class GetPurchaseAttemptView(object):

	def __init__(self, request):
		self.request = request

	def __call__(self):
		request = self.request
		username = request.authenticated_userid
		values = CaseInsensitiveDict(request.params)
		purchase_id = values.get('purchaseID') or values.get('purchase_id')
		if not purchase_id:
			msg = _("Must specify a valid purchase attempt id")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = purchase_history.get_purchase_attempt(purchase_id, username)
		if purchase is None:
			raise hexc.HTTPNotFound(detail=_('Purchase attempt not found'))
		elif purchase.is_pending():
			start_time = purchase.StartTime
			if time.time() - start_time >= 90 and not purchase.is_synced():
				_sync_purchase(purchase)

		result = LocatedExternalDict({'Items':[purchase],
									  'Last Modified':purchase.lastModified})
		return result

@view_config(name="get_purchasables", **_view_defaults)
class GetPurchasablesView(object):

	def __init__(self, request):
		self.request = request

	def __call__(self):
		purchasables = list(purchasable.get_all_purchasables())
		for p in list(purchasables):
			if hasattr(p, 'HACK_make_acl'):
				acl = p.HACK_make_acl()
				class Dummy(object):
					__acl__ = None
				dummy = Dummy()
				dummy.__acl__ = acl
				policy = ACLAuthorizationPolicy()
				principals = self.request.effective_principals
				if not policy.permits(dummy, principals, nauth.ACT_READ):
					logger.debug('Removing purchasable %s', p)
					purchasables.remove(p)

		result = LocatedExternalDict({'Items': purchasables, 'Last Modified':0})
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=store_interfaces.IPurchasable,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class PurchasableGetView(GenericGetView):
	pass

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=store_interfaces.IPurchaseAttempt,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class PurchaseAttemptGetView(GenericGetView):

	def __call__(self):
		purchase = super(PurchaseAttemptGetView, self).__call__()
		if purchase.is_pending():
			start_time = purchase.StartTime
			if time.time() - start_time >= 90 and not purchase.is_synced():
				_sync_purchase(purchase)
		return purchase

# post views

@view_config(name="price_purchasable", **_post_view_defaults)
class PricePurchasableView(AbstractPostView):

	def price(self, purchasable_id, quantity):
		pricer = component.getUtility(store_interfaces.IPurchasablePricer)
		source = priceable.create_priceable(purchasable_id, quantity)
		result = pricer.price(source)
		return result

	def price_purchasable(self, values=None):
		values = values or self.readInput()
		purchasable_id = values.get('purchasableID') or values.get('purchasable_id', u'')

		# check quantity
		quantity = values.get('quantity', 1)
		if not is_valid_pve_int(quantity):
			raise hexc.HTTPBadRequest(_('Invalid quantity'))
		quantity = int(quantity)

		try:
			result = self.price(purchasable_id, quantity)
			return result
		except InvalidPurchasable:
			raise hexc.HTTPUnprocessableEntity(_('Purchasable not found'))

	def __call__(self):
		result = self.price_purchasable()
		return result

@view_config(name="redeem_purchase_code", **_post_view_defaults)
class RedeemPurchaseCodeView(AbstractPostView):

	def __call__(self):
		request = self.request
		values = self.readInput()
		purchasable_id = values.get('purchasableID') or values.get('purchasable_id')
		if not purchasable_id:
			msg = _("Must specify a valid purchasable id")
			raise hexc.HTTPUnprocessableEntity(msg)

		invitation_code = values.get('invitationCode', values.get('invitation_code'))
		if not invitation_code:
			msg = _("Must specify a valid invitation code")
			raise hexc.HTTPUnprocessableEntity(msg)

		try:
			purchase = invitations.get_purchase_by_code(invitation_code)
		except ValueError:
			# improper key
			purchase = None

		if purchase is None or not store_interfaces.IPurchaseAttempt.providedBy(purchase):
			raise hexc.HTTPNotFound(detail=_('Purchase attempt not found'))

		if purchase.Quantity is None:
			raise hexc.HTTPUnprocessableEntity(detail=_('Not redeemable purchase'))

		if purchasable_id not in purchase.Items:
			msg = _("The invitation code is not for this purchasable")
			raise hexc.HTTPUnprocessableEntity(msg)

		username = request.authenticated_userid
		try:
			invite = \
				invitations.create_store_purchase_invitation(purchase, invitation_code)
			invite.accept(username)
		except invitations.InvitationAlreadyAccepted:
			msg = _("The invitation code has already been accepted")
			raise hexc.HTTPUnprocessableEntity(msg)
		except invitations.InvitationCapacityExceeded:
			msg = _("There are no remaining invitations for this code")
			raise hexc.HTTPUnprocessableEntity(msg)

		return hexc.HTTPNoContent()

# object get views

del _view_defaults
del _post_view_defaults
