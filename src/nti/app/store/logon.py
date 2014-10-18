#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface
from zope import component

from pyramid.interfaces import IRequest

from nti.appserver.interfaces import IMissingUser
from nti.appserver.interfaces import ILogonLinkProvider
from nti.appserver.interfaces import IAuthenticatedUserLinkProvider
from nti.appserver.interfaces import IUnauthenticatedUserLinkProvider

from nti.dataserver.links import Link
from nti.dataserver.interfaces import IUser

from . import STORE

class _BaseStoreLinkProvider(object):

	def __init__(self, request):
		self.request = request

	def get_links(self):
		elements = (STORE, 'gift_stripe_payment')
		root = self.request.route_path('objects.generic.traversal', traverse=())
		root = root[:-1] if root.endswith('/') else root
		return [Link(root, elements=elements, rel='gift_stripe_payment')]

@interface.implementer(IUnauthenticatedUserLinkProvider)
@component.adapter(IRequest)
class _StoreUnauthenticatedUserLinkProvider(_BaseStoreLinkProvider):
	pass

@interface.implementer(IAuthenticatedUserLinkProvider)
@component.adapter(IUser, IRequest)
class _StoreAuthenticatedUserLinkProvider(_BaseStoreLinkProvider):

	def __init__(self, user, request):
		super(_StoreAuthenticatedUserLinkProvider, self).__init__(request)
		self.user = user

@interface.implementer(ILogonLinkProvider)
@component.adapter(IMissingUser, IRequest)
class _StoreMissingUserLinkProvider(_StoreAuthenticatedUserLinkProvider):

	def __call__(self):
		links = self.get_links()
		return links[0] if links else None
