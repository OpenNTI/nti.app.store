#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from . import MessageFactory as _

import simplejson as json

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.dataserver import authorization as nauth

from nti.store import admin_views
from nti.store import purchase_history

from nti.utils.maps import CaseInsensitiveDict

from . import views

class AbstractPostView(object):

	def __init__(self, request):
		self.request = request

	def readInput(self):
		request = self.request
		body = self.request.body
		result = CaseInsensitiveDict()
		if body:
			try:
				values = json.loads(unicode(body, request.charset))
			except UnicodeError:
				values = json.loads(unicode(body, 'iso-8859-1'))
			result.update(**values)
		return result

class _BasePostPurchaseAttemptView(AbstractPostView):

	def __call__(self):
		values = self.readInput()
		purchase_id = values.get('purchaseid') or values.get('purchase_id')
		if not purchase_id:
			msg = _("Must specify a valid purchase attempt id")
			raise hexc.HTTPUnprocessableEntity(msg)
			
		purchase = purchase_history.get_purchase_attempt(purchase_id)
		if not purchase:
			raise hexc.HTTPNotFound(detail=_('Purchase attempt not found'))
		return purchase

_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=views.StorePathAdapter,
					  request_method='GET')
_view_admin_defaults = _view_defaults.copy()
_view_admin_defaults['permission'] = nauth.ACT_MODERATE

_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

_admin_view_defaults = _post_view_defaults.copy()
_admin_view_defaults['permission'] = nauth.ACT_MODERATE

@view_config(name="get_content_roles", **_view_admin_defaults)
class GetContentRolesView(admin_views.GetContentRolesView):
	""" return the a list /w the content roles """

@view_config(name="permission_purchasable", **_admin_view_defaults)
class PermissionPurchasableView(admin_views.PermissionPurchasableView):
	""" permission a purchasable """

@view_config(name="unpermission_purchasable", **_admin_view_defaults)
class UnPermissionPurchasableView(admin_views.UnPermissionPurchasableView):
	""" Unpermission a purchasable """

@view_config(name="delete_purchase_attempt", **_admin_view_defaults)
class DeletePurchaseAttemptView(_BasePostPurchaseAttemptView):

	def __call__(self):
		purchase = super(DeletePurchaseAttemptView, self).__call__()
		purchase_history.remove_purchase_attempt(purchase, purchase.creator)
		logger.info("Purchase attempt '%s' has been deleted")
		return hexc.HTTPNoContent()

@view_config(name="delete_purchase_history", **_admin_view_defaults)
class DeletePurchaseHistoryView(admin_views.DeletePurchaseHistoryView):
	""" delete a purchase history """

@view_config(name="get_users_purchase_history", **_view_admin_defaults)
class GetUsersPurchaseHistoryView(admin_views.GetUsersPurchaseHistoryView):
	""" get users purchase history """

@view_config(name="generate_purchase_invoice", **_admin_view_defaults)
class GeneratePurchaseInvoice(admin_views.GeneratePurchaseInvoice):
	""" generate a purchase invoice """
	
del _view_defaults
del _post_view_defaults
del _admin_view_defaults
del _view_admin_defaults
