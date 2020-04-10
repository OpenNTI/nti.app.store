#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904
from collections import OrderedDict

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_item
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import starts_with

from zope.component.hooks import getSite

from zope.securitypolicy.interfaces import IPrincipalRoleManager

from nti.app.store import DEFAULT_STRIPE_KEY_ALIAS

from nti.store.payments.stripe.model import PersistentStripeConnectKey

from nti.store.payments.stripe.storage import get_stripe_key_container

does_not = is_not

from six.moves import urllib_parse

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.appserver.workspaces import UserService

from nti.dataserver.authorization import ROLE_SITE_ADMIN

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
            store_wss = next(x for x in ext_object['Items']
                         if x['Title'] == 'store')
            assert_that(store_wss['Items'],
                        has_item(has_entry('Links', has_length(15))))

            # Catalog
            assert_that(ext_object['Items'],
                        has_item(has_entry('Title', 'Catalog')))
            catalog_ws = next(x for x in ext_object['Items']
                         if x['Title'] == 'Catalog')
            self.require_link_href_with_rel(catalog_ws, 'redeem_purchase_code')

    def _query_params(self, url):
        url_parts = list(urllib_parse.urlparse(url))
        # Query params are in index 4
        return OrderedDict(urllib_parse.parse_qsl(url_parts[4]))

    def _assign_role_for_site(self, role, username, site=None):
        role_manager = IPrincipalRoleManager(site or getSite())
        role_name = getattr(role, "id", role)
        role_manager.assignRoleToPrincipal(role_name, username)

    @WithSharedApplicationMockDS(users=True)
    def test_external_site_admin(self):
        with mock_dataserver.mock_db_trans(self.ds, site_name="mathcounts.nextthought.com"):
            self._assign_role_for_site(ROLE_SITE_ADMIN, 'sjohnson@nextthought.com')

            user = User.get_user(dataserver=self.ds,
                                 username=u'sjohnson@nextthought.com')
            service = UserService(user)
            ext_object = toExternalObject(service)

            assert_that(ext_object['Items'],
                        has_item(has_entry('Title', 'store')))
            store_wss = next(x for x in ext_object['Items']
                         if x['Title'] == 'store')
            store_coll = next(x for x in store_wss['Items']
                             if x['Title'] == 'store')
            assert_that(store_coll,
                        has_entry('Links', has_length(16)))
            stripe_account_link = self.link_href_with_rel(store_coll,
                                                          'connect_stripe_account')
            assert_that(stripe_account_link,
                        is_("/dataserver2/++etc++hostsites/mathcounts.nextthought.com/++etc++site/StripeConnectKeys/@@stripe_connect_oauth1"))
            assert_that(self._query_params(stripe_account_link),
                        has_length(0))

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
            user = User.get_user(dataserver=self.ds,
                                 username=u'sjohnson@nextthought.com')
            service = UserService(user)
            ext_object = toExternalObject(service)

            store_wss = next(x for x in ext_object['Items']
                         if x['Title'] == 'store')
            store_coll = next(x for x in store_wss['Items']
                             if x['Title'] == 'store')
            disconnect_stripe_link = self.link_with_rel(store_coll,
                                                        'disconnect_stripe_account')
            assert_that(disconnect_stripe_link['method'],
                        starts_with("DELETE"))
            assert_that(disconnect_stripe_link['href'],
                        starts_with("/dataserver2/++etc++hostsites/mathcounts.nextthought.com/++etc++site/StripeConnectKeys/default"))
