#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_not
does_not = is_not

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.store.tests import ApplicationStoreTestLayer

class TestStoreViews(ApplicationLayerTest):

	layer = ApplicationStoreTestLayer

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_purchasables(self):
		url = '/dataserver2/Purchasables/xx'
		self.testapp.get(url, status=404)
