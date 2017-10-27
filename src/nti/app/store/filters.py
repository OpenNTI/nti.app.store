#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import interface

from nti.dataserver.interfaces import ICreatableObjectFilter

from nti.store.utils import PURCHASE_ATTEMPT_MIME_TYPES

logger = __import__('logging').getLogger(__name__)


@interface.implementer(ICreatableObjectFilter)
class _StoreContentObjectFilter(object):

    def __init__(self, context=None):
        pass

    def filter_creatable_objects(self, terms):
        for name in tuple(terms):  # mutating
            if name in PURCHASE_ATTEMPT_MIME_TYPES:
                terms.pop(name, None)
        return terms
