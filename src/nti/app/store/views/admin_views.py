#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
import six
import isodate
from io import BytesIO
from datetime import datetime

from requests.structures import CaseInsensitiveDict

from zope import component

from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error as raise_error

from nti.app.store import MessageFactory as _

from nti.app.store.utils import to_boolean
from nti.app.store.utils import parse_datetime
from nti.app.store.utils import AbstractPostView
from nti.app.store.utils import is_valid_pve_int

from nti.app.store.views import StorePathAdapter

from nti.app.store.views.view_mixin import GeneratePurchaseInvoiceViewMixin

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IShardLayout

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.site.hostpolicy import get_host_site
from nti.site.hostpolicy import get_all_host_sites

from nti.store.index import IX_CREATOR
from nti.store.index import IX_MIMETYPE
from nti.store.index import get_purchase_catalog
from nti.store.index import create_purchase_catalog

from nti.store.interfaces import PA_STATE_SUCCESS
from nti.store.interfaces import PAYMENT_PROCESSORS

from nti.store.interfaces import IPurchasable
from nti.store.interfaces import IPurchaseAttempt
from nti.store.interfaces import IPurchaseHistory
from nti.store.interfaces import IPurchasablePricer

from nti.store.purchase_attempt import create_purchase_attempt

from nti.store.purchase_order import create_purchase_item
from nti.store.purchase_order import create_purchase_order

from nti.store.purchasable import get_purchasable

from nti.store.store import get_gift_code
from nti.store.store import get_gift_registry
from nti.store.store import get_invitation_code
from nti.store.store import get_purchase_history
from nti.store.store import get_gift_purchase_history

from nti.store.utils import PURCHASE_ATTEMPT_MIME_TYPES

from nti.zodb import is_broken

TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


def _tx_string(s):
    if s is not None and isinstance(s, six.string_types):
        s = s.encode('utf-8')
    return s


@view_config(name="GetUsersPurchaseHistory")
@view_config(name="get_users_purchase_history")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=StorePathAdapter,
               request_method='GET')
class GetUsersPurchaseHistoryView(AbstractAuthenticatedView):

    def __call__(self):
        request = self.request
        params = CaseInsensitiveDict(request.params)
        purchasable = params.get('ntiid') \
            or params.get('purchasable') \
            or params.get('purchasableId')
        if purchasable and get_purchasable(purchasable) is None:
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': _(u"Purchasable not found."),
                            'field': 'purchasable'
                        },
                        None)

        all_failed = to_boolean(params.get('failed'))
        all_succeeded = to_boolean(params.get('succeeded'))

        catalog = get_purchase_catalog()
        mime_types = PURCHASE_ATTEMPT_MIME_TYPES
        intids_purchases = catalog[IX_MIMETYPE].apply({'any_of': mime_types})

        usernames = params.get('usernames') or params.get('username')
        if usernames:
            usernames = [x.lower() for x in usernames.split(",")]
            creator_intids = catalog[IX_CREATOR].apply({'any_of': usernames})
            intids_purchases = catalog.family.IF.intersection(intids_purchases,
                                                              creator_intids)

        stream = BytesIO()
        writer = csv.writer(stream)
        response = request.response
        response.content_encoding = 'identity'
        response.content_type = 'text/csv; charset=UTF-8'
        response.content_disposition = 'attachment; filename="purchases.csv"'

        header = ["username", 'name', 'email', 'transaction',
                  'date', 'amount', 'status']
        writer.writerow(header)

        intids = component.getUtility(IIntIds)
        for uid in intids_purchases or ():
            purchase = intids.queryObject(uid)
            if not IPurchaseAttempt.providedBy(purchase) \
                    or is_broken(purchase, uid):
                continue

            if purchasable and purchasable not in purchase.Items:
                continue

            if (all_succeeded and not purchase.has_succeeded()) \
                    or (all_failed and not purchase.has_failed()):
                continue

            status = purchase.State
            code = get_invitation_code(purchase)
            startTime = purchase.StartTime
            date = isodate.date_isoformat(datetime.fromtimestamp(startTime))
            pricing = purchase.Pricing
            amount = getattr(pricing, 'TotalPurchasePrice', None) or u''

            creator = purchase.creator
            username = getattr(creator, 'username', creator).lower()
            profile = purchase.profile
            email = getattr(profile, 'email', None) or u''
            name = getattr(profile, 'realname', None) or username

            row_data = [username, name, email, code, date, amount, status]
            writer.writerow([_tx_string(x) for x in row_data])

        stream.flush()
        stream.seek(0)
        response.body_file = stream
        return response


@view_config(name="GetUsersGiftHistory")
@view_config(name="get_users_gift_history")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=StorePathAdapter,
               request_method='GET')
class GetUsersGiftHistoryView(AbstractAuthenticatedView):

    def __call__(self):
        request = self.request
        params = CaseInsensitiveDict(request.params)
        usernames = params.get('username') or params.get('usernames')
        if usernames:
            usernames = set(usernames.split(","))

        all_failed = to_boolean(params.get('failed'))
        all_succeeded = to_boolean(params.get('succeeded'))

        end_time = parse_datetime(params.get('endTime', None))
        start_time = parse_datetime(params.get('startTime', None))

        stream = BytesIO()
        writer = csv.writer(stream)
        response = request.response
        response.content_encoding = 'identity'
        response.content_type = 'text/csv; charset=UTF-8'
        response.content_disposition = 'attachment; filename="gifts.csv"'

        header = ["transaction", "from", 'sender', 'to',
                  'receiver', 'date', 'amount', 'status']
        writer.writerow(header)

        registry = get_gift_registry()
        for username in registry.keys():
            if usernames and username not in usernames:
                continue
            purchases = get_gift_purchase_history(username,
                                                  end_time=end_time,
                                                  start_time=start_time)
            if all_succeeded:
                purchases = (p for p in purchases if p.has_succeeded())
            elif all_failed:
                purchases = (p for p in purchases if p.has_failed())

            for p in purchases:
                start_time = datetime.fromtimestamp(p.StartTime)
                started = isodate.date_isoformat(start_time)
                amount = getattr(p.Pricing, 'TotalPurchasePrice', None) or u''
                row_data = [get_gift_code(p),
                            username,
                            p.SenderName,
                            p.Receiver,
                            p.ReceiverName,
                            started,
                            amount,
                            p.State]
                writer.writerow([_tx_string(x) for x in row_data])

        stream.flush()
        stream.seek(0)
        response.body_file = stream
        return response


# post views


@view_config(name="GeneratePurchaseInvoice")
@view_config(name="generate_purchase_invoice")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=StorePathAdapter,
               request_method='POST')
class GeneratePurchaseInvoiceView(AbstractPostView,  # order matters
                                  GeneratePurchaseInvoiceViewMixin):
    pass


@view_config(name="CreateInvitationPurchase")
@view_config(name="create_invitation_purchase")
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               context=StorePathAdapter,
               request_method='POST')
class CreateInviationPurchaseAttemptView(AbstractPostView):

    def price_order(self, order):
        pricer = component.getUtility(IPurchasablePricer)
        result = pricer.evaluate(order)
        return result

    def price_purchase(self, purchase):
        result = self.price_order(purchase.Order)
        return result

    def create_purchase_attempt(self, item, quantity=None, expirationTime=None,
                                processor=None):
        state = PA_STATE_SUCCESS
        p_item = create_purchase_item(item, 1)
        p_order = create_purchase_order(p_item, quantity=quantity)
        purchase = create_purchase_attempt(p_order,
                                           state=state,
                                           processor=processor,
                                           expiration=expirationTime)
        purchase.Pricing = self.price_purchase(purchase)
        return purchase

    def __call__(self):
        values = self.readInput()
        purchasable_id = values.get('item') \
            or values.get('ntiid') \
            or values.get('purchasable') \
            or values.get('purchasableId')
        if not purchasable_id:
            msg = _(u"Must specify a valid purchasable.")
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': msg,
                            'field': 'purchasable'
                        },
                        None)

        purchase = get_purchasable(purchasable_id)
        if not purchase:
            msg = _(u'Purchasable not found')
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': msg,
                            'field': 'purchasable'
                        },
                        None)

        quantity = values.get('quantity') or 0
        if not is_valid_pve_int(quantity):
            msg = _(u'Must specify a valid quantity.')
            raise_error(self.request,
                        hexc.HTTPUnprocessableEntity,
                        {
                            'message': msg,
                            'field': 'quantity'
                        },
                        None)

        expiration = values.get('expiry') \
            or values.get('expiration') \
            or values.get('expirationTime') \
            or values.get('expirationDate')
        if expiration:
            expirationTime = parse_datetime(expiration, safe=True)
            if expirationTime is None:
                msg = _(u'Invalid expiration date/time.')
                raise_error(self.request,
                            hexc.HTTPUnprocessableEntity,
                            {
                                'message': msg,
                                'field': 'quantity'
                            },
                            None)
                raise hexc.HTTPUnprocessableEntity(msg)
        else:
            expirationTime = None

        user = self.remoteUser
        hist = IPurchaseHistory(user)
        processor = values.get('processor') or PAYMENT_PROCESSORS[0]
        purchase = self.create_purchase_attempt(purchasable_id,
                                                quantity=quantity,
                                                processor=processor,
                                                expirationTime=expirationTime)
        hist.add_purchase(purchase)

        logger.info("Invitation purchase %s created for user %s. " +
                    "Redemption(s) %s. Expiration %s",
                    get_invitation_code(purchase),
                    user, quantity, expiration)
        return purchase


@view_config(name='RebuildPurchaseCatalog')
@view_config(name='rebuild_purchase_catalog')
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               context=StorePathAdapter,
               permission=nauth.ACT_NTI_ADMIN)
class RebuildPurchaseCatalogView(AbstractAuthenticatedView):

    def index_item(self, doc_id, obj, catalog, seen):
        items = list(obj.Items or ())
        if len(items) == 1 and items[0] in seen:
            name = seen[items[0]]
            with current_site(get_host_site(name)):
                catalog.index_doc(doc_id, obj)
        else:
            found = False
            for site in get_all_host_sites():
                with current_site(site):
                    for item in items:
                        purchasable = component.queryUtility(IPurchasable,
                                                             name=item)
                        if purchasable is not None:
                            found = True
                            seen[item] = site.__name__
                            catalog.index_doc(doc_id, obj)
            if not found:  # should not happen
                catalog.index_doc(doc_id, obj)

    def __call__(self):
        intids = component.getUtility(IIntIds)
        # remove indexes
        catalog = get_purchase_catalog()
        for name, index in list(catalog.items()):
            intids.unregister(index)
            del catalog[name]
        # recreate indexes
        create_purchase_catalog(catalog, family=intids.family)
        for index in catalog.values():
            intids.register(index)
        # reindex user purchase history
        count = 0
        seen = dict()
        dataserver = component.getUtility(IDataserver)
        users_folder = IShardLayout(dataserver).users_folder
        for user in users_folder.values():
            history = get_purchase_history(user, False)
            for attempt in history or ():
                doc_id = intids.queryId(attempt)
                if doc_id is not None:
                    self.index_item(doc_id, attempt, catalog, seen)
                    count += 1
        # reindex gift registry
        registry = get_gift_registry()
        for container in registry.values():
            for obj in container.values():
                doc_id = intids.queryId(attempt)
                if doc_id is not None:
                    self.index_item(doc_id, obj, catalog, seen)
                    count += 1
        result = LocatedExternalDict()
        result[ITEM_COUNT] = result[TOTAL] = count
        return result
