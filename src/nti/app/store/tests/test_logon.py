#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import has_length
from hamcrest import assert_that

from pyramid.testing import DummyRequest

from nti.app.store.logon import _BaseStoreLinkProvider

from nti.app.testing.application_webtest import ApplicationLayerTest


class TestLogon(ApplicationLayerTest):

    def test_link_for_user(self):
        provider = _BaseStoreLinkProvider(DummyRequest())
        links = provider.get_links()
        assert_that(links, has_length(10))
