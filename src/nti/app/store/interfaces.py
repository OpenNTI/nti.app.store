#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.appserver.workspaces.interfaces import IWorkspace


class IStoreWorkspace(IWorkspace):
    """
    A workspace containing data for store.
    """
