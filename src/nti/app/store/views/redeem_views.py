#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

from zope import component

from zope.event import notify

from zope.proxy import ProxyBase

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.appserver.interfaces import INewObjectTransformer

from nti.common.functional import identity

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import StandardExternalFields

from nti.store.purchasable import get_purchasable

from nti.store.store import get_purchase_by_code

from nti.store.invitations import InvitationExpired
from nti.store.invitations import InvitationAlreadyAccepted
from nti.store.invitations import InvitationCapacityExceeded
from nti.store.invitations import create_store_purchase_invitation

from nti.store.store import get_purchase_attempt

from nti.store.interfaces import IRedemptionError
from nti.store.interfaces import IGiftPurchaseAttempt
from nti.store.interfaces import IPurchasableChoiceBundle
from nti.store.interfaces import IInvitationPurchaseAttempt
from nti.store.interfaces import GiftPurchaseAttemptRedeemed

from ..utils import AbstractPostView

from ..utils import to_boolean

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

class PurchaseAttemptProxy(ProxyBase):
	
	Items = property(
					lambda s: s.__dict__.get('_v_items'),
					lambda s, v: s.__dict__.__setitem__('_v_items', v))
	
	def __new__(cls, base, *args, **kwargs):
		return ProxyBase.__new__(cls, base)

	def __init__(self, base, items=None):
		ProxyBase.__init__(self, base)
		self.Items = items

def find_redeemable_purchase(code):
	try:
		purchase = get_purchase_by_code(code)
	except ValueError:
		purchase = None
	return purchase

def redeem_invitation_purchase(user, code, purchasable, vendor_updates=None, request=None):
	purchase = find_redeemable_purchase(code)
	if not IInvitationPurchaseAttempt.providedBy(purchase):
		raise hexc.HTTPNotFound(detail=_('Purchase attempt not found.'))

	if purchasable not in purchase.Items:
		msg = _("The code is not for this purchasable.")
		raise hexc.HTTPUnprocessableEntity(msg)

	try:
		invite = create_store_purchase_invitation(purchase, code)
		invite.accept(user.username)
		# returned redeemed purchase attempt
		purchase_id = purchase.linked_purchase_id(user)
		purchase = get_purchase_attempt(purchase_id)
		# set vendor updates
		if vendor_updates is not None:
			purchase.Context['AllowVendorUpdates'] = vendor_updates
	except InvitationAlreadyAccepted:
		msg = _("The invitation code has already been accepted.")
		raise hexc.HTTPUnprocessableEntity(msg)
	except InvitationCapacityExceeded:
		msg = _("There are no remaining invitations for this code.")
		raise hexc.HTTPUnprocessableEntity(msg)
	except InvitationExpired:
		msg = _("This invitation is expired.")
		raise hexc.HTTPUnprocessableEntity(msg)
	return purchase

def redeem_gift_purchase(user, code, item=None, vendor_updates=None, request=None):
	purchase = find_redeemable_purchase(code)
	if IInvitationPurchaseAttempt.providedBy(purchase): # legacy cases
		return redeem_invitation_purchase(user, code, 
										  request=request,
										  purchasable=item,
										  vendor_updates=vendor_updates)

	if not IGiftPurchaseAttempt.providedBy(purchase):
		raise hexc.HTTPNotFound(detail=_('Purchase attempt not found.'))

	if purchase.is_redeemed():
		msg = _("Gift purchase already redeemed.")
		raise hexc.HTTPUnprocessableEntity(msg)
	
	# set vendor updates before called notify
	if vendor_updates is not None:
		purchase.Context['AllowVendorUpdates'] = vendor_updates

	purchasables = {get_purchasable(x) for x in purchase.Items}
	purchasables.discard(None)
	if not purchasables:
		msg = _("No valid purchasables found.")
		raise hexc.HTTPUnprocessableEntity(msg)
	elif len(purchase.Items) != len(purchasables):
		msg = _("Purchase contain missing purchasables.")
		raise hexc.HTTPUnprocessableEntity(msg)
	elif len(purchasables) == 1: ## check for bundle choice
		purchasable = purchasables.__iter__().next()
		if IPurchasableChoiceBundle.providedBy(purchasable):
			if not item:
				msg = _("Must specify a redeemable item.")
				raise hexc.HTTPUnprocessableEntity(msg)
			if item not in purchase.Items:
				msg = _("The redeemable item is not in this purchasable.")
				raise hexc.HTTPUnprocessableEntity(msg)
			## proxy purchase
			purchase = PurchaseAttemptProxy(purchase, (item,))
	notify(GiftPurchaseAttemptRedeemed(purchase, user, request=request))
	return purchase

def _transform_object(obj, request=None):
	try:
		transformer = component.queryMultiAdapter( (request, obj),
												   INewObjectTransformer )
		if transformer is None:
			transformer = component.queryAdapter( obj,
												  INewObjectTransformer,
												  default=identity)

		result = transformer( obj )
		return result
	except Exception:
		logger.warn("Failed to transform incoming object", exc_info=True)
		return obj
		
@view_config(name="redeem_purchase_code", **_post_view_defaults)
class RedeemPurchaseCodeView(AbstractPostView):

	def __call__(self):
		values = self.readInput()
		purchasable = 	values.get('purchasable') or \
						values.get('purchasableId')
		if not purchasable:
			msg = _("Must specify a valid purchasable id.")
			raise hexc.HTTPUnprocessableEntity(msg)

		invitation_code = values.get('invitationCode') or \
						  values.get('invitation') or \
 						  values.get('code')
		if not invitation_code:
			msg = _("Must specify a valid invitation code.")
			raise hexc.HTTPUnprocessableEntity(msg)

		purchase = redeem_invitation_purchase(	self.remoteUser, 
												invitation_code,
								  				purchasable=purchasable,
								 				request=self.request)
		return purchase

@view_config(name="redeem_gift", **_post_view_defaults)
class RedeemGiftView(AbstractPostView):

	def __call__(self):
		values = self.readInput()
		gift_code = values.get('code') or \
					values.get('gift') or \
					values.get('giftCode')
		if not gift_code:
			msg = _("Must specify a valid gift code.")
			raise hexc.HTTPUnprocessableEntity(msg)

		allow_vendor_updates = 	values.get('AllowVendorUpdates') or \
								values.get('allow_vendor_updates')
		if allow_vendor_updates is not None:
			allow_vendor_updates = to_boolean(allow_vendor_updates)

		item = values.get('purchasable') or values.get('item')
		try:
			result = redeem_gift_purchase(self.remoteUser, 
									 	  gift_code,
									 	  item=item,
									 	  request=self.request,
										  vendor_updates=allow_vendor_updates)
			result = _transform_object(result, self.request)
		except hexc.HTTPNotFound:
			self.request.response.status_int = 404
			result = IRedemptionError(_('Gift/Invitation not found.'))
		except hexc.HTTPUnprocessableEntity as e:
			result = IRedemptionError(e.detail)
			self.request.response.status_int = 422
		except ValueError as e:
			result = IRedemptionError(e)
			self.request.response.status_int = 409
		return result

# object get views

del _view_defaults
del _post_view_defaults
