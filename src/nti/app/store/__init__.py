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

from nti.site.runner import get_possible_site_names


#: Store path
STORE = 'store'

#: Stripe path
STRIPE = 'stripe'

#: Purchasables path
PURCHASABLES = 'purchasables'
