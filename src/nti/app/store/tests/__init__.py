#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from nti.testing.layers import GCLayerMixin
from nti.testing.layers import ZopeComponentLayer
from nti.testing.layers import ConfiguringLayerMixin
from nti.dataserver.tests.mock_dataserver import DSInjectorMixin

from nti.app.testing.layers import PyramidLayerMixin
from nti.app.testing.application_webtest import Library
from nti.app.testing.application_webtest import AppCreatingLayerHelper

class ApplicationStoreTestLayer(ZopeComponentLayer,
								PyramidLayerMixin,
								ConfiguringLayerMixin,
								DSInjectorMixin):
	features = ('forums',)
	set_up_packages = (('store_config.zcml', 'nti.app.store.tests'),)

	APP_IN_DEVMODE = True

	# We have no packages, but we will set up the listeners ourself
	# when configuring the app
	configure_events = False

	@classmethod
	def _setup_library(cls, *args, **kwargs):
		return Library()

	@classmethod
	def _extra_app_settings(cls):
		return {}

	@classmethod
	def setUp(cls):
		AppCreatingLayerHelper.appSetUp(cls)

	@classmethod
	def tearDown(cls):
		AppCreatingLayerHelper.appTearDown(cls)

	@classmethod
	def testSetUp(cls, test=None):
		AppCreatingLayerHelper.appTestSetUp(cls, test)

	@classmethod
	def testTearDown(cls, test=None):
		AppCreatingLayerHelper.appTestTearDown(cls, test)
