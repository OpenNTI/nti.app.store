#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope import component
from zope import lifecycleevent

from zope.component.hooks import getSite

from zope.file.file import File

from zope.intid.interfaces import IIntIds

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.contentfile import validate_sources

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.externalization.view_mixins import BatchingUtilsMixin
from nti.app.externalization.view_mixins import ModeledContentEditRequestUtilsMixin
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.store import MessageFactory as _

from nti.app.store.views import PurchasablesPathAdapter

from nti.appserver.policies.interfaces import ISitePolicyUserEventListener

from nti.common.random import generate_random_hex_string

from nti.coremetadata.interfaces import SYSTEM_USER_ID

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import notifyModified

from nti.ntiids.ntiids import make_ntiid
from nti.ntiids.ntiids import make_specific_safe
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.interfaces import IHostPolicyFolder

from nti.site.site import get_component_hierarchy_names

from nti.store import PURCHASABLE

from nti.store.index import IX_SITE
from nti.store.index import IX_ITEMS
from nti.store.index import get_purchase_catalog

from nti.store.interfaces import IPurchasable
from nti.store.interfaces import IPurchaseAttempt

from nti.store.store import get_purchasable
from nti.store.store import get_purchasables
from nti.store.store import remove_purchasable
from nti.store.store import register_purchasable

from nti.traversal.traversal import find_interface

from nti.zodb.containers import time_to_64bit_int

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
MIMETYPE = StandardExternalFields.MIMETYPE
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


def validate_purchasble_items(purchasable, request=None):
    for item in purchasable.Items:
        obj = find_object_with_ntiid(item)
        if obj is None:
            logger.error("Cannot find item %s", item)
            raise_error(request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u'Cannot find purchasable item.'),
                            'field': 'Items'
                        },
                        None)


def get_namedfile(source, name='icon.dat'):
    contentType = getattr(source, 'contentType', None)
    contentType = contentType or 'application/octet-stream'
    filename = getattr(source, 'filename', None) \
            or getattr(source, 'name', name)
    result = File(contentType)
    result.filename = filename
    with result.open("w") as fp:
        fp.write(source.read())
    return result


def handle_multipart(contentObject, sources, provided=IPurchasable):
    for name, source in sources.items():
        if name in provided:
            namedfile = get_namedfile(source)
            setattr(contentObject, name, namedfile)


def get_provider():
    policy = component.queryUtility(ISitePolicyUserEventListener)
    provider = getattr(policy, 'PROVIDER', None) or u'NTI'
    return provider


@view_config(route_name='objects.generic.traversal',
             context=PurchasablesPathAdapter,
             request_method='POST',
             permission=nauth.ACT_CONTENT_EDIT,
             renderer='rest')
class CreatePurchasableView(AbstractAuthenticatedView,
                            ModeledContentUploadRequestUtilsMixin):

    content_predicate = IPurchasable.providedBy

    def _make_tiid(self, nttype, creator=SYSTEM_USER_ID):
        provider = get_provider()
        current_time = time_to_64bit_int(time.time())
        extra = generate_random_hex_string(6)
        specific_base = '%s.%s.%s' % (creator, current_time, extra)
        specific = make_specific_safe(specific_base)
        ntiid = make_ntiid(nttype=nttype,
                           provider=provider,
                           specific=specific)
        return ntiid

    def _createObject(self):
        externalValue = self.readInput()
        if not externalValue.get(NTIID):
            ntiid = self._make_tiid(PURCHASABLE)
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
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u'Purchasable already created.'),
                        },
                        None)
        validate_purchasble_items(purchasable, self.request)
        lifecycleevent.created(purchasable)

        # add object to conenction
        register_purchasable(purchasable)
        purchasable.__parent__ = getSite()
        self.request.response.status_int = 201
        return purchasable


def get_purchases_for_items(*purchasables):
    catalog = get_purchase_catalog()
    intids = component.getUtility(IIntIds)
    query = {
        IX_ITEMS: {'any_of': purchasables},
        IX_SITE: {'any_of': get_component_hierarchy_names()},
    }
    for doc_id in catalog.apply(query) or ():
        obj = intids.queryObject(doc_id)
        if IPurchaseAttempt.providedBy(obj):
            yield obj


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

    def readInput(self, value=None):
        result = ModeledContentUploadRequestUtilsMixin.readInput(self, value)
        result.pop(NTIID, None)
        result.pop('ntiid', None)
        return result

    def __call__(self):
        theObject = self.request.context
        self._check_object_exists(theObject)
        self._check_object_unmodified_since(theObject)

        # save old items
        old_items = set(theObject.Items)

        externalValue = self.readInput()
        self.updateContentObject(theObject, externalValue, notify=False)

        validate_purchasble_items(theObject)

        # check if items have been changed
        new_items = set(theObject.Items)
        if old_items.difference(new_items):
            purchases = count_purchases_for_items(theObject.NTIID)
            if purchases: # there are purchases
                raise_error(self.request,
                            hexc.HTTPUnprocessableEntity,
                            {    
                                'message': _(u'Cannot change purchasable items.'),
                            },
                            None)

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
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {    
                            'message': _(u'Cannot delete purchasable.'),
                        },
                        None)

        # raise removed event
        folder = find_interface(purchasable, IHostPolicyFolder, strict=False)
        registry = folder.getSiteManager() if folder is not None else None
        remove_purchasable(purchasable, registry=registry)
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


@view_config(route_name='objects.generic.traversal',
             context=IPurchasable,
             request_method='GET',
             permission=nauth.ACT_CONTENT_EDIT,
             name="purchases",
             renderer='rest')
class PurchasablePurchasesView(AbstractAuthenticatedView,
                               BatchingUtilsMixin):

    _DEFAULT_BATCH_SIZE = 30
    _DEFAULT_BATCH_START = 0
    
    def __call__(self):
        result = LocatedExternalDict()
        result.__name__ = self.request.view_name
        result.__parent__ = self.request.context
        purchases = list(get_purchases_for_items(self.context.NTIID))
        purchases.sort(key=lambda x: x.StartTime, reverse=True)
        result['TotalItemCount'] = len(purchases)
        self._batch_items_iterable(result, purchases)
        result[ITEM_COUNT] = len(result[ITEMS])
        return result
    

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
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result
