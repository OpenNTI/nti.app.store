#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import zope.i18nmessageid
MessageFactory = zope.i18nmessageid.MessageFactory('nti.dataserver')

from nti.site.runner import get_possible_site_names


#: Store path
STORE = 'store'

#: Stripe path
STRIPE = 'stripe'

#: Keys path
REGISTERED_STRIPE_KEYS = 'keys'

#: Payeezy path
PAYEEZY = 'payeezy'

#: Purchasables path
PURCHASABLES = 'purchasables'

DEFAULT_STRIPE_KEY_ALIAS = u'default'
