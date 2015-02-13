#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

from nti.appserver.workspaces.interfaces import IWorkspace

class IStoreWorkspace(IWorkspace):
	"""
	A workspace containing data for store.
	"""
