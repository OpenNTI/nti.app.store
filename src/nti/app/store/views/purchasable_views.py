#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory as _

from urllib import unquote

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.container.contained import Contained

from zope.traversing.interfaces import IPathAdapter

from ZODB.interfaces import IConnection

from pyramid.view import view_config
from pyramid.view import view_defaults
from pyramid.interfaces import IRequest
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentEditRequestUtilsMixin
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IGlobalContentPackageLibrary

from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverFolder

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.schema.interfaces import find_most_derived_interface

from nti.site.interfaces import IHostPolicySiteManager

from nti.store.interfaces import IPurchasable
from nti.store.purchasable import get_purchasable

from .. import PURCHASABLES

from . import StorePathAdapter

@interface.implementer(IPathAdapter)
@component.adapter(IDataserverFolder, IRequest)
class PurchasablesPathAdapter(Contained):

	def __init__(self, dataserver, request):
		self.__parent__ = dataserver
		self.__name__ = PURCHASABLES

	def __getitem__(self, ntiid):
		if not ntiid:
			raise hexc.HTTPNotFound()

		ntiid = unquote(ntiid)
		result = get_purchasable(ntiid)
		if result is not None:
			return result
		raise KeyError(ntiid)

def _registry():
	library = component.queryUtility(IContentPackageLibrary)
	if IGlobalContentPackageLibrary.providedBy(library):
		registry = component.getGlobalSiteManager()
	else:
		registry = component.getSiteManager()
	return registry

def registerUtility(registry, component, provided, name):
	if IHostPolicySiteManager.providedBy(registry):
		return registry.subscribedRegisterUtility(component,
									 			  provided=provided,
									 			  name=name)
	else:
		return registry.registerUtility(component,
									 	provided=provided,
									 	name=name)

def unregisterUtility(registry, provided, name):
	if IHostPolicySiteManager.providedBy(registry):
		return registry.subscribedUnregisterUtility(provided=provided, name=name)
	else:
		return registry.unregisterUtility(provided=provided, name=name)
	
def validate_purchasble_items(purchasable):
	for item in purchasable.Items:
		obj = find_object_with_ntiid(item)
		if obj is None:
			logger.error("Cannot find item %s", item)
			raise hexc.HTTPUnprocessableEntity(_('Cannot find purchasable item'))

@view_config(name="CreatePurchasable")
@view_config(name="create_purchasable")
@view_defaults(	route_name='objects.generic.traversal',
			  	context=StorePathAdapter,
			 	request_method='POST',
			 	permission=nauth.ACT_NTI_ADMIN,
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
			raise hexc.HTTPUnprocessableEntity(_('Purchasable already created'))
		validate_purchasble_items(purchasable)
		lifecycleevent.created(purchasable)
		
		## add object to conenction
		registry = _registry()
		provided = find_most_derived_interface(purchasable, IPurchasable)
		registerUtility(registry, purchasable, provided, purchasable.NTIID)
		
		IConnection(registry).add(purchasable)
		lifecycleevent.added(purchasable) # get an iid
		
		self.request.response.status_int =  201
		return purchasable

@view_config(route_name='objects.generic.traversal',
			 context=IPurchasable,
			 request_method='PUT',
			 permission=nauth.ACT_NTI_ADMIN,
			 renderer='rest')
class UpdatePurchasableView(AbstractAuthenticatedView,
							ModeledContentEditRequestUtilsMixin,
 						 	ModeledContentUploadRequestUtilsMixin):

	content_predicate = IPurchasable.providedBy
	
	def __call__(self):
		theObject = self._get_object_to_update()
		self._check_object_exists( theObject )
		self._check_object_unmodified_since( theObject )
		
		externalValue = self.readInput()
		self.updateContentObject(theObject, externalValue, notify=False)
		
		validate_purchasble_items(theObject)
		lifecycleevent.modified(theObject)
		
		return theObject
