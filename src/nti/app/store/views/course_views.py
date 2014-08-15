#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

from .. import MessageFactory as _

logger = __import__('logging').getLogger(__name__)

import itertools

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.dataserver import authorization as nauth

from nti.store.interfaces import ICourse
from nti.store.enrollment import enroll_course
from nti.store.enrollment import unenroll_course
from nti.store.enrollment import CourseNotFoundException
from nti.store.enrollment import UserNotEnrolledException
from nti.store.enrollment import InvalidEnrollmentAttemptException

from . import StorePathAdapter
from . import GetPurchasablesView
from .._utils import AbstractPostView

_view_defaults = dict(route_name='objects.generic.traversal',
					  renderer='rest',
					  permission=nauth.ACT_READ,
					  context=StorePathAdapter,
					  request_method='GET')
_post_view_defaults = _view_defaults.copy()
_post_view_defaults['request_method'] = 'POST'

@view_config(name="get_courses", **_view_defaults)
class GetCoursesView(GetPurchasablesView):

	def __call__(self):
		result = super(GetCoursesView, self).__call__()
		purchasables = result['Items']
		courses = list(itertools.ifilter(ICourse.providedBy, purchasables))
		result['Items'] = courses
		return result

@view_config(name="enroll_course", **_post_view_defaults)
class EnrollCourseView(AbstractPostView):

	def enroll(self, values=None):
		values = values or self.readInput()
		username = self.request.authenticated_userid
		course_id = values.get('courseID') or values.get('course_id') or u''
		description = values.get('description', u'')
		try:
			enroll_course(username, course_id, description, self.request)
		except CourseNotFoundException:
			raise hexc.HTTPUnprocessableEntity(_('Course not found'))

		return hexc.HTTPNoContent()

	def __call__(self):
		result = self.enroll()
		return result

@view_config(name="unenroll_course", **_post_view_defaults)
class UnenrollCourseView(AbstractPostView):

	def unenroll(self, values=None):
		values = values or self.readInput()
		username = self.request.authenticated_userid
		course_id = values.get('courseID') or values.get('course_id') or u''
		try:
			unenroll_course(username, course_id, self.request)
		except CourseNotFoundException:
			logger.error("Course %s not found" % course_id)
			raise hexc.HTTPUnprocessableEntity(_('Course not found'))
		except UserNotEnrolledException:
			logger.error("User %s not enrolled in %s" % (username, course_id))
			raise hexc.HTTPUnprocessableEntity(_('User not enrolled'))
		except InvalidEnrollmentAttemptException:
			raise hexc.HTTPUnprocessableEntity(_('Invalid enrollment attempt'))

		return hexc.HTTPNoContent()

	def __call__(self):
		result = self.unenroll()
		return result

del _view_defaults
del _post_view_defaults
