#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

# from nti.externalization.externalization import to_json_representation

from nti.appserver.tests.test_application import SharedApplicationTestBase, WithSharedApplicationMockDS

from hamcrest import (assert_that, has_length, has_entry, has_key, greater_than_or_equal_to, none, is_not)

class TestStoreCourseViews(SharedApplicationTestBase):

	set_up_packages = SharedApplicationTestBase.set_up_packages + (('store_config.zcml', 'nti.appserver.store.tests'),)

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_courses(self):
		url = '/dataserver2/store/get_courses'
		res = self.testapp.get(url, status=200)
		json_body = res.json_body
		assert_that(json_body, has_key('Items'))
		assert_that(json_body, has_entry('Last Modified', 0))
		items = json_body['Items']
		assert_that(items, has_length(greater_than_or_equal_to(1)))
		for course in items:
			assert_that(course, has_entry('NTIID', is_not(none())))
			assert_that(course, has_entry('Links', has_length(1)))
			assert_that(course['Links'][0], has_entry('rel', 'enroll'))

# 	@WithSharedApplicationMockDS(users=True, testapp=True)
# 	def test_enroll_course(self):
# 		url = '/dataserver2/store/enroll_course'
# 		res = self.testapp.get(url, status=200)
# 		json_body = res.json_body
# 		assert_that(json_body, has_key('Items'))
# 		assert_that(json_body, has_entry('Last Modified', 0))
# 		items = json_body['Items']
# 		assert_that(items, has_length(greater_than_or_equal_to(1)))
# 		for course in items:
# 			assert_that(course, has_entry('NTIID', is_not(none())))
# 			assert_that(course, has_entry('Links', has_length(1)))
# 			assert_that(course['Links'][0], has_entry('rel', 'enroll'))
