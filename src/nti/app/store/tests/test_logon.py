#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

import unittest

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS


class TestLogon(ApplicationLayerTest):

    @unittest.skip("This tries to contact OU LDAP server, it's not a unit test")
    @WithSharedApplicationMockDS(testapp=True, users=None)
    def test_link_for_user(self):
        testapp = self.testapp
        res = testapp.post('/dataserver2/logon.handshake?username=madd2844',
                           extra_environ={'HTTP_ORIGIN': 'http://platform.ou.edu'})
        self.require_link_href_with_rel(res.json_body, 'get_purchasables')
        self.require_link_href_with_rel(res.json_body, 'gift_stripe_payment')
        self.require_link_href_with_rel(res.json_body,
                                        'gift_stripe_payment_preflight')
        self.require_link_href_with_rel(res.json_body,
                                        'get_gift_pending_purchases')
        self.require_link_href_with_rel(res.json_body, 'price_purchasable')
        self.require_link_href_with_rel(res.json_body,
                                        'price_purchasable_with_stripe_coupon')
