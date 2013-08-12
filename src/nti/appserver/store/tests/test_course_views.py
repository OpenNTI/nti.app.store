#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from nti.dataserver import users

from nti.externalization.externalization import to_json_representation

from nti.dataserver.tests import mock_dataserver
from nti.appserver.tests.test_application import SharedApplicationTestBase, WithSharedApplicationMockDS

from hamcrest import (assert_that, has_length, has_entry, has_key, greater_than_or_equal_to, none, is_not, is_in, is_)

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

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_enroll_unenroll_course(self):
		username = self.extra_environ_default_user.lower()
		with mock_dataserver.mock_db_trans(self.ds):
			user = users.User.get_user(username)
			comm = users.Community.create_community(self.ds, username='OU')
			user.record_dynamic_membership(comm)
			user.follow(comm)

		path = '/dataserver2/store/enroll_course'
		data = to_json_representation({'courseId': 'tag:nextthought.com,2011-10:OU-course-CLC3403LawAndJustice'})
		res = self.testapp.post(path, data)
		assert_that(res.status_int, is_(204))

		with mock_dataserver.mock_db_trans(self.ds):
			user = users.User.get_user(username)
			assert_that('OU', is_in(user.usernames_of_dynamic_memberships))

		path = '/dataserver2/store/unenroll_course'
		res = self.testapp.post(path, data)
		assert_that(res.status_int, is_(204))

		with mock_dataserver.mock_db_trans(self.ds):
			user = users.User.get_user(username)
			assert_that('OU', is_not(is_in(user.usernames_of_dynamic_memberships)))

