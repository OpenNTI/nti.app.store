#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.namedfile.constraints import FileConstraints

from nti.namedfile.interfaces import IFileConstraints

from nti.store.interfaces import IPurchasable

@component.adapter(IPurchasable)
@interface.implementer(IFileConstraints)
class _PurchasableFileConstraints(FileConstraints):
	max_files = 1
	max_file_size = 10485760  # 10 MB
