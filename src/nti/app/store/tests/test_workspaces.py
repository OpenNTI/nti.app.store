#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_not
from hamcrest import has_item
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
does_not = is_not

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.appserver.workspaces import UserService

from nti.dataserver.tests import mock_dataserver

from nti.dataserver.users.users import User

from nti.externalization.externalization import toExternalObject


class TestWorkspaces(ApplicationLayerTest):

    @WithSharedApplicationMockDS(users=True)
    def test_external(self):
        with mock_dataserver.mock_db_trans(self.ds):
            user = User.get_user(dataserver=self.ds,
                                 username=u'sjohnson@nextthought.com')
            service = UserService(user)
            ext_object = toExternalObject(service)

            assert_that(ext_object['Items'],
                        has_item(has_entry('Title', 'store')))
            store_wss = [x for x in ext_object['Items']
                         if x['Title'] == 'store']
            assert_that(store_wss, has_length(1))
            store_wss, = store_wss
            assert_that(store_wss['Items'],
                        has_item(has_entry('Links', has_length(15))))
