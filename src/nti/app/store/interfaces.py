#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from nti.appserver.workspaces.interfaces import IWorkspace


class IStoreWorkspace(IWorkspace):
    """
    A workspace containing data for store.
    """
