#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope import component
from zope import lifecycleevent

from zope.intid.interfaces import IIntIds

from plone.namedfile.file import getImageInfo

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.contentfile import validate_sources

from nti.app.externalization.view_mixins import ModeledContentEditRequestUtilsMixin
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.store import MessageFactory as _

from nti.app.store.views import PurchasablesPathAdapter

from nti.common.random import generate_random_hex_string

from nti.coremetadata.interfaces import SYSTEM_USER_ID

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import notifyModified

from nti.namedfile.file import NamedBlobFile
from nti.namedfile.file import NamedBlobImage

from nti.ntiids.ntiids import make_ntiid
from nti.ntiids.ntiids import make_specific_safe
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.store import get_purchase_catalog

from nti.store.interfaces import IPurchasable

from nti.store.purchase_index import IX_ITEMS

from nti.store.store import get_purchasable
from nti.store.store import get_purchasables
from nti.store.store import remove_purchasable
from nti.store.store import register_purchasable

from nti.store.utils import get_ntiid_type

from nti.zodb.containers import time_to_64bit_int

from nti.zope_catalog.catalog import ResultSet

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
MIMETYPE = StandardExternalFields.MIMETYPE

def validate_purchasble_items(purchasable):
	for item in purchasable.Items:
		obj = find_object_with_ntiid(item)
		if obj is None:
			logger.error("Cannot find item %s", item)
			raise hexc.HTTPUnprocessableEntity(_('Cannot find purchasable item.'))

def get_namedfile(source, name='icon.dat'):
	contentType = getattr(source, 'contentType', None)
	if contentType:
		factory = NamedBlobFile
	else:
		contentType, _, _ = getImageInfo(source)
		source.seek(0)  # reset
		factory = NamedBlobImage if contentType else NamedBlobFile
	contentType = contentType or u'application/octet-stream'
	filename = getattr(source, 'filename', None) or getattr(source, 'name', name)
	result = factory(filename=filename, data=source.read(), contentType=contentType)
	return result

def handle_multipart(contentObject, sources, provided=IPurchasable):
	for name, source in sources.items():
		if name in provided:
			namedfile = get_namedfile(source)
			setattr(contentObject, name, namedfile)

@view_config(route_name='objects.generic.traversal',
			 context=PurchasablesPathAdapter,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class CreatePurchasableView(AbstractAuthenticatedView,
 						 	ModeledContentUploadRequestUtilsMixin):

	content_predicate = IPurchasable.providedBy

	def _make_tiid(self, nttype, creator=SYSTEM_USER_ID):
		current_time = time_to_64bit_int(time.time())
		creator = getattr(creator, 'username', creator)
		extra = generate_random_hex_string(6)
		specific_base = '%s.%s.%s' % (creator, current_time, extra)
		specific = make_specific_safe(specific_base)
		ntiid = make_ntiid(nttype=nttype,
					   	   provider='NTI',
						   specific=specific)
		return ntiid

	def _createObject(self):
		externalValue = self.readInput()
		if not externalValue.get(NTIID):
			nttype = get_ntiid_type(externalValue.get(MIMETYPE))
			if not nttype:
				raise hexc.HTTPUnprocessableEntity(_('Invalid purchasable MimeType.'))
			ntiid = self._make_tiid(nttype, self.remoteUser)
			externalValue[NTIID] = ntiid
		datatype = self.findContentType(externalValue)
		result = self.createAndCheckContentObject(owner=None,
										  		  creator=None,
										  		  datatype=datatype,
										  		  externalValue=externalValue)
		self.updateContentObject(result, externalValue, notify=False)
		# check for multi-part data
		sources = get_all_sources(self.request)
		if sources:
			validate_sources(self.remoteUser, result, sources)
			handle_multipart(result, sources)
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
	return ResultSet(items_ids, intids, True)

def count_purchases_for_items(*purchasables):
	result = get_purchases_for_items(*purchasables)
	return result.count()

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
			purchases = count_purchases_for_items(theObject.NTIID)
			if purchases:  # there are purchases
				raise hexc.HTTPUnprocessableEntity(_('Cannot change purchasable items.'))

		notifyModified(theObject, externalValue)
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
		purchases = count_purchases_for_items(purchasable.NTIID)
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
		if not theObject.isPublic():
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
		if theObject.isPublic():
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
