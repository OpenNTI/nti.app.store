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

from pyramid.threadlocal import get_current_request

from nti.dataserver.links import Link

from nti.externalization.singleton import SingletonDecorator
from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator

from nti.contentlibrary import interfaces as lib_interfaces

from nti.store.interfaces import IPurchasable
from nti.store.purchase_history import is_item_activated
from nti.store.purchase_history import has_history_by_item

from nti.deprecated import hiding_warnings
with hiding_warnings():
	from nti.store.interfaces import ICourse

from . import STORE

LINKS = StandardExternalFields.LINKS

@component.adapter(IPurchasable)
@interface.implementer(IExternalObjectDecorator)
class _PurchasableDecorator(object):

	__metaclass__ = SingletonDecorator

	def set_links(self, request, username, original, external):
		if original.Amount and request:
			ds2 = request.path_info_peek()
			ds_path = '/%s/%s/' % (ds2, STORE)
			links = external.setdefault(LINKS, [])

			# insert history link
			if has_history_by_item(username, original.NTIID):
				history_path = ds_path + 'get_purchase_history?purchasableID=%s'
				history_href = history_path % urllib.quote(original.NTIID)
				link = Link(history_href, rel="history")
				interface.alsoProvides(link, ILocation)
				links.append(link)

			# insert price link
			price_href = ds_path + 'price_purchasable'
			link = Link(price_href, rel="price", method='Post')
			interface.alsoProvides(link, ILocation)
			links.append(link)

	def add_library_details(self, original, external):
		library = component.queryUtility(lib_interfaces.IContentPackageLibrary)
		unit = library.get(original.NTIID) if library else None
		if not original.Title:
			external['Title'] = unit.title if unit else u''
		if not original.Description:
			external['Description'] = unit.title if unit else u''

	def add_activation(self, username, original, external):
		activated = is_item_activated(username, original.NTIID)
		# XXX: FIXME: Hack for some borked objects, hopefully only in alpha database
		# See purchase_history for more details
		if activated and ICourse.providedBy(original):
			# We can easily get out of sync here if the purchase object
			# itself has been removed/lost. This will result in logging a
			# warning if so.
			from nti.store import enrollment
			activated = enrollment.is_enrolled(username, original.NTIID)
		external['Activated'] = activated

	def decorateExternalObject(self, original, external):
		request = get_current_request()
		username = request.authenticated_userid if request else None
		if username:
			self.add_activation(username, original, external)
			self.set_links(request, username, original, external)
		self.add_library_details(original, external)

@component.adapter(ICourse)
@interface.implementer(IExternalObjectDecorator)
class _CourseDecorator(_PurchasableDecorator):

	def set_links(self, request, username, original, external):
		if original.Amount is not None:
			super(_CourseDecorator, self).set_links(request,
													username,
													original,
													external)
		elif request:
			ds2 = request.path_info_peek()
			ds_path = '/%s/%s/' % (ds2, STORE)
			if not has_history_by_item(username, original.NTIID):
				erroll_path = ds_path + 'enroll_course'
				link = Link(erroll_path, rel="enroll", method='Post')
			else:
				unerroll_path = ds_path + 'unenroll_course'
				link = Link(unerroll_path, rel="unenroll", method='Post')
			interface.alsoProvides(link, ILocation)
			external.setdefault(LINKS, []).append(link)
