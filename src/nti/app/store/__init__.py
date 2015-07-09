#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import zope.i18nmessageid
MessageFactory = zope.i18nmessageid.MessageFactory('nti.dataserver')

from pyramid.threadlocal import get_current_request

STORE = 'store'
STRIPE = 'stripe'
PURCHASABLES = 'purchasables'

def get_possible_site_names(request=None, include_default=True):
	request = request or get_current_request()
	if not request:
		return () if not include_default else ('',)
	site_names = getattr(request, 'possible_site_names', ())
	if include_default:
		site_names += ('',)
	return site_names
get_site_names = get_possible_site_names
