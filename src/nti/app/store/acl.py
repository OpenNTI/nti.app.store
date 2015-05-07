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

from nti.common.property import Lazy

from nti.dataserver import authorization
from nti.dataserver.authorization_acl import ace_allowing

from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.interfaces import EVERYONE_USER_NAME

# from nti.contenttypes.courses.interfaces import ICourseCatalog
# from nti.contenttypes.courses.interfaces import ICourseInstance
# from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
# 
# from nti.contenttypes.presentation.interfaces import INTIAudio
# from nti.contenttypes.presentation.interfaces import INTIVideo
# from nti.contenttypes.presentation.interfaces import INTISlideDeck
# from nti.contenttypes.presentation.interfaces import IPresentationAsset
# from nti.contenttypes.presentation.interfaces import INTILessonOverview
# 
# from nti.dataserver.interfaces import ACE_DENY_ALL
# from nti.dataserver.interfaces import AUTHENTICATED_GROUP_NAME
# 
# from nti.dataserver.authorization import ACT_READ
# from nti.dataserver.authorization_acl import ace_allowing
# from nti.dataserver.authorization_acl import acl_from_aces
# 
# from nti.ntiids.ntiids import find_object_with_ntiid
# 
# from nti.traversal.traversal import find_interface

from nti.store.interfaces import IPurchasable

@component.adapter(IPurchasable)
@interface.implementer(IACLProvider)
class PurchasableACLProvider(object):

    def __init__(self, context):
        self.context = context

    @Lazy
    def __acl__(self):
        return (ace_allowing(EVERYONE_USER_NAME, authorization.ACT_READ, self),)