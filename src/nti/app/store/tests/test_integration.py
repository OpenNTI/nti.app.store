#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from hamcrest import assert_that
from hamcrest import is_
from hamcrest import starts_with

from zope.component.hooks import getSite

from zope.securitypolicy.interfaces import IPrincipalRoleManager

from nti.app.store import DEFAULT_STRIPE_KEY_ALIAS

from nti.dataserver.authorization import ROLE_SITE_ADMIN

from nti.dataserver.tests import mock_dataserver

from nti.store.payments.stripe.model import PersistentStripeConnectKey

from nti.store.payments.stripe.storage import get_stripe_key_container

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS


class TestIntegration(ApplicationLayerTest):

    def _assign_role_for_site(self, role, username, site=None):
        role_manager = IPrincipalRoleManager(site or getSite())
        role_name = getattr(role, "id", role)
        role_manager.assignRoleToPrincipal(role_name, username)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_integration_success(self):
        with mock_dataserver.mock_db_trans(self.ds, site_name="mathcounts.nextthought.com"):
            self._assign_role_for_site(ROLE_SITE_ADMIN, 'sjohnson@nextthought.com')

        url = "/dataserver2/users/sjohnson@nextthought.com/Integration/Integrations/stripe"
        res = self.testapp.get(url,
                               extra_environ={
                                   b'HTTP_ORIGIN': b'http://mathcounts.nextthought.com'
                               })

        href = self.link_href_with_rel(res.json_body, 'connect_stripe_account')
        assert_that(href, is_("/dataserver2/++etc++hostsites/mathcounts.nextthought.com/++etc++site/StripeConnectKeys/@@stripe_connect_oauth1"))

        with mock_dataserver.mock_db_trans(self.ds, site_name="mathcounts.nextthought.com"):
            key_container = get_stripe_key_container()
            connect_key = PersistentStripeConnectKey(
                Alias=DEFAULT_STRIPE_KEY_ALIAS,
                StripeUserID=u"user_id_1",
                LiveMode=False,
                PrivateKey=u"private_key_1",
                RefreshToken=u"refresh_token_1",
                PublicKey=u"public_key_1",
                TokenType=u"bearer"
            )
            key_container.add_key(connect_key)

        res = self.testapp.get(url,
                               extra_environ={
                                   b'HTTP_ORIGIN': b'http://mathcounts.nextthought.com'
                               })

        disconnect_stripe_link = self.link_with_rel(res.json_body,
                                                    'disconnect_stripe_account')
        assert_that(disconnect_stripe_link['method'],
                    starts_with("DELETE"))
        assert_that(disconnect_stripe_link['href'],
                    starts_with(
                        "/dataserver2/++etc++hostsites/mathcounts.nextthought.com/++etc++site/StripeConnectKeys/default"))

