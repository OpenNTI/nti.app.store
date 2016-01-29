#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import lifecycleevent

from zope.intid.interfaces import IIntIds

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import ModeledContentEditRequestUtilsMixin
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.store import MessageFactory as _

from nti.app.store.views import PurchasablesPathAdapter

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.store import get_purchase_catalog

from nti.store.interfaces import IPurchasable

from nti.store.purchase_index import IX_ITEMS

from nti.store.store import get_purchasable
from nti.store.store import get_purchasables
from nti.store.store import remove_purchasable
from nti.store.store import register_purchasable

from nti.zope_catalog.catalog import ResultSet

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID

def validate_purchasble_items(purchasable):
	for item in purchasable.Items:
		obj = find_object_with_ntiid(item)
		if obj is None:
			logger.error("Cannot find item %s", item)
			raise hexc.HTTPUnprocessableEntity(_('Cannot find purchasable item.'))

@view_config(route_name='objects.generic.traversal',
			 context=PurchasablesPathAdapter,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class CreatePurchasableView(AbstractAuthenticatedView,
 						 	ModeledContentUploadRequestUtilsMixin):

	content_predicate = IPurchasable.providedBy

	def _createObject(self):
		externalValue = self.readInput()
		datatype = self.findContentType(externalValue)
		result = self.createAndCheckContentObject(owner=None,
										  		  creator=None,
										  		  datatype=datatype,
										  		  externalValue=externalValue)
		self.updateContentObject(result, externalValue, notify=False)
		return result

	def __call__(self):
		purchasable = self._createObject()
		if get_purchasable(purchasable.NTIID) != None:
			raise hexc.HTTPUnprocessableEntity(_('Purchasable already created.'))
		validate_purchasble_items(purchasable)
		lifecycleevent.created(purchasable)

		# add object to conenction
		register_purchasable(purchasable)
		self.request.response.status_int = 201
		return purchasable

def get_purchases_for_items(*purchasables):
	catalog = get_purchase_catalog()
	intids = component.getUtility(IIntIds)
	items_ids = catalog[IX_ITEMS].apply({'any_of': purchasables})
	result = ResultSet(items_ids, intids, ignore_invalid=True)
	return result

@view_config(route_name='objects.generic.traversal',
			 context=IPurchasable,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class UpdatePurchasableView(AbstractAuthenticatedView,
							ModeledContentEditRequestUtilsMixin,
 						 	ModeledContentUploadRequestUtilsMixin):

	content_predicate = IPurchasable.providedBy

	def __call__(self):
		theObject = self.request.context
		self._check_object_exists(theObject)
		self._check_object_unmodified_since(theObject)

		# save old items
		old_items = set(theObject.Items)

		externalValue = self.readInput()
		externalValue.pop(NTIID, None)  # don't allow  updating ntiid
		self.updateContentObject(theObject, externalValue, notify=False)

		validate_purchasble_items(theObject)

		# check if items have been changed
		new_items = set(theObject.Items)
		if old_items.difference(new_items):
			purchases = get_purchases_for_items(theObject.NTIID)
			if purchases:  # there are purchases
				raise hexc.HTTPUnprocessableEntity(_('Cannot change purchasable items.'))

		lifecycleevent.modified(theObject)
		return theObject

@view_config(route_name='objects.generic.traversal',
			 context=IPurchasable,
			 request_method='DELETE',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class DeletePurchasableView(AbstractAuthenticatedView,
							ModeledContentEditRequestUtilsMixin):

	def __call__(self):
		purchasable = self.request.context
		self._check_object_exists(purchasable)
		self._check_object_unmodified_since(purchasable)

		# check if items have been changed
		purchases = get_purchases_for_items(purchasable.NTIID)
		if purchases:  # there are purchases
			raise hexc.HTTPUnprocessableEntity(_('Cannot delete purchasable.'))

		registry = purchasable.__parent__  # parent site manager
		remove_purchasable(purchasable, registry=registry)  # raise removed event
		return hexc.HTTPNoContent()

@view_config(route_name='objects.generic.traversal',
			 context=IPurchasable,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT,
			 name="enable",
			 renderer='rest')
class EnablePurchasableView(AbstractAuthenticatedView,
							ModeledContentEditRequestUtilsMixin):

	def __call__(self):
		theObject = self.request.context
		self._check_object_exists(theObject)
		self._check_object_unmodified_since(theObject)
		if not theObject.Public:
			theObject.Public = True
			lifecycleevent.modified(theObject)
		return theObject

@view_config(route_name='objects.generic.traversal',
			 context=IPurchasable,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT,
			 name="disable",
			 renderer='rest')
class DisablePurchasableView(AbstractAuthenticatedView,
							 ModeledContentEditRequestUtilsMixin):

	def __call__(self):
		theObject = self.request.context
		self._check_object_exists(theObject)
		self._check_object_unmodified_since(theObject)
		if theObject.Public:
			theObject.Public = False
			lifecycleevent.modified(theObject)
		return theObject

@view_config(name="collection")
@view_defaults(route_name='objects.generic.traversal',
			 context=PurchasablesPathAdapter,
			 request_method='GET',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class AllPurchasablesView(AbstractAuthenticatedView):

	def __call__(self):
		result = LocatedExternalDict()
		items = result[ITEMS] = get_purchasables()
		result['ItemCount'] = result['Total'] = len(items)
		return result
