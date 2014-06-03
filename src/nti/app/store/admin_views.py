#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from pyramid.view import view_config

from nti.dataserver import authorization as nauth

from nti.store import admin_views

from . import views

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
class DeletePurchaseAttemptView(admin_views.DeletePurchaseAttemptView):
	""" delete a purchase attempt """

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
