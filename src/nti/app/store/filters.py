#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.appserver.interfaces import ICreatableObjectFilter

from nti.store.utils import PURCHASE_ATTEMPT_MIME_TYPES


@interface.implementer(ICreatableObjectFilter)
class _StoreContentObjectFilter(object):

    def __init__(self, context=None):
        pass

    def filter_creatable_objects(self, terms):
        for name in tuple(terms):  # mutating
            if name in PURCHASE_ATTEMPT_MIME_TYPES:
                terms.pop(name, None)
        return terms
