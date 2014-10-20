#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import urllib

from zope import interface
from zope import component
from zope.container.interfaces import ILocation

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.dataserver.links import Link

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object
from nti.externalization.interfaces import IExternalObjectDecorator

from nti.store.interfaces import IPurchasable
from nti.store.purchase_history import is_item_activated
from nti.store.purchase_history import has_history_by_item
from nti.store.payments.stripe.interfaces import IStripeConnectKey

from . import STORE

LINKS = StandardExternalFields.LINKS
		
@component.adapter(IPurchasable)
@interface.implementer(IExternalObjectDecorator)
class _PurchasableDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def set_links(self, username, original, external):
		if original.Amount:
			request = self.request
			ds2 = request.path_info_peek()
			ds_path = '/%s/%s/' % (ds2, STORE)
			links = external.setdefault(LINKS, [])

			# insert history link
			if has_history_by_item(username, original.NTIID):
				history_href = ds_path + 'get_purchase_history'
				quoted = urllib.quote(original.NTIID)
				link = Link(history_href, rel="history", method='GET',
							params={'purchasableID': quoted})
				interface.alsoProvides(link, ILocation)
				links.append(link)

			# insert price link
			price_href = ds_path + 'price_purchasable'
			link = Link(price_href, rel="price", method='Post')
			interface.alsoProvides(link, ILocation)
			links.append(link)

	def add_activation(self, username, original, external):
		activated = is_item_activated(username, original.NTIID)
		external['Activated'] = activated

	def _do_decorate_external(self, original, external):
		username = self.remoteUser.username
		self.add_activation(username, original, external)
		self.set_links(username, original, external)

@component.adapter(IPurchasable)
@interface.implementer(IExternalObjectDecorator)
class _StripePurchasableDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def set_links(self, original, external):
		if original.Amount:
			request = self.request
			ds2 = request.path_info_peek()
			ds_path = '/%s/%s/' % (ds2, STORE)
			links = external.setdefault(LINKS, [])
			
			href = ds_path + 'price_purchasable_with_stripe_coupon'
			link = Link(href, rel="price_with_stripe_coupon", method='POST')
			interface.alsoProvides(link, ILocation)
			links.append(link)
			
			quoted = urllib.quote(original.Provider)
			href = ds_path + 'get_stripe_connect_key'
			link = Link(href, rel="get_stripe_connect_key", method='GET',
						params={'provider':quoted})
			interface.alsoProvides(link, ILocation)
			links.append(link)
			
			href = ds_path + 'create_stripe_token'
			link = Link(href, rel="create_stripe_token", method='POST')
			interface.alsoProvides(link, ILocation)
			links.append(link)
			
			href = ds_path + 'post_stripe_payment'
			link = Link(href, rel="post_stripe_payment", method='POST')
			interface.alsoProvides(link, ILocation)
			links.append(link)
			
			if original.Giftable:
				href = ds_path + 'gift_stripe_payment'
				link = Link(href, rel="gift_stripe_payment", method='POST')
				interface.alsoProvides(link, ILocation)
				links.append(link)

	def _do_decorate_external(self, original, external):
		keyname = original.Provider
		result = component.queryUtility(IStripeConnectKey, keyname)
		if result is not None:
			self.set_links(original, external)
			external['StripeConnectKey'] = to_external_object(result)
		