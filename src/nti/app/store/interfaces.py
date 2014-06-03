#!/usr/bin/env python
# -*- coding: utf-8 -*
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

from nti.appserver import interfaces as app_interfaces

class IStoreWorkspace(app_interfaces.IWorkspace):
	"""
	A workspace containing data for store.
	"""
