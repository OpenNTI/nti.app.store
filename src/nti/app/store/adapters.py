#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from pyramid.interfaces import IRequest

from zope import component
from zope import interface

from nti.contentfolder.interfaces import IPathAdapter

from nti.namedfile.constraints import FileConstraints

from nti.namedfile.interfaces import IFileConstraints

from nti.site.interfaces import IHostPolicySiteManager

from nti.store.interfaces import IPurchasable

from nti.store.payments.stripe.storage import get_stripe_key_container

logger = __import__('logging').getLogger(__name__)


@component.adapter(IPurchasable)
@interface.implementer(IFileConstraints)
class _PurchasableFileConstraints(FileConstraints):
    max_files = 1
    max_file_size = 10485760  # 10 MB


@interface.implementer(IPathAdapter)
@component.adapter(IHostPolicySiteManager, IRequest)
def StripeConnectKeysPathAdapter(site_manager, request):
    return get_stripe_key_container()
