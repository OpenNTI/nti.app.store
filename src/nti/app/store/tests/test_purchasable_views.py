#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import assert_that
from hamcrest import has_entries
does_not = is_not

import fudge
from urllib import quote

from nti.externalization.interfaces import StandardExternalFields

from nti.store.purchasable import get_purchasable

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.store.tests import ApplicationStoreTestLayer

import nti.dataserver.tests.mock_dataserver as mock_dataserver

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID

class TestStoreViews(ApplicationLayerTest):

	layer = ApplicationStoreTestLayer
	
	purchasalbe = {
		'Amount': 300.0,
		'Author': u'CMU',
		'BulkPurchase': True,
		'Class': 'Purchasable',
		'Currency': u'USD',
		'Description': u'04-630: Computer Science for Practicing Engineers',
		'Discountable': True,
		'Fee': None,
		'Giftable': False,
		'Icon': u'http://cmu.edu/',
		'IsPurchasable': True,
		'Items': [u'tag:nextthought.com,2011-10:CMU-HTML-04630_main'],
		'License': u'1 Year License',
		'MimeType': 'application/vnd.nextthought.store.purchasable',
		'NTIID': u'tag:nextthought.com,2011-10:CMU-purchasable-computer_science_for_practicing_engineer',
		'Provider': u'CMU',
		'Public': True,
		'Redeemable': False}
	
	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_get_legacy_purchasable(self):
		ntiid = "tag:nextthought.com,2011-10:CMU-HTML-04630_main.04_630:_computer_science_for_practicing_engineers"
		url = '/dataserver2/Purchasables/%s' % ntiid
		self.testapp.get(url, status=200)

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.purchasable_views.validate_purchasble_items')
	def test_create_purchasable(self, mock_vp):
		mock_vp.is_callable().with_args().returns(None)
				
		ntiid = u'tag:nextthought.com,2011-10:CMU-purchasable-computer_science_for_practicing_engineer'

		with mock_dataserver.mock_db_trans(self.ds):
			p = get_purchasable(ntiid)
			assert_that(p, is_(none()))
		
		ext_obj = dict(self.purchasalbe)
		ext_obj[NTIID] = ntiid
		
		url = '/dataserver2/store/create_purchasable'
		res = self.testapp.post_json(url, ext_obj, status=201)
		assert_that(res.json_body, 
					has_entries('OID', is_not(none()),
								'Amount', is_(300.0),
								'NTIID', ntiid ) )

		with mock_dataserver.mock_db_trans(self.ds):
			p = get_purchasable(ntiid)
			assert_that(p, is_not(none()))

		# try to post again
		self.testapp.post_json(url, ext_obj, status=422)

	@WithSharedApplicationMockDS(users=True, testapp=True)
	@fudge.patch('nti.app.store.views.purchasable_views.validate_purchasble_items',
				 'nti.app.store.views.purchasable_views.get_purchases_for_items')
	def test_update_purchasable(self, mock_vp, mock_gpi):
		mock_vp.is_callable().with_args().returns(None)
		mock_gpi.is_callable().with_args().returns(None)
		
		ntiid = u'tag:nextthought.com,2011-10:CMU-purchasable-peaky_blinders'
		
		ext_obj = dict(self.purchasalbe)
		ext_obj[NTIID] = ntiid
		ext_obj[ITEMS] = list(ext_obj[ITEMS])
		
		url = '/dataserver2/store/create_purchasable'
		self.testapp.post_json(url, ext_obj, status=201)
		
		# update
		url = '/dataserver2/Purchasables/%s' % quote(ntiid)
		ext_obj[ITEMS] =  [u'tag:nextthought.com,2011-10:CMU-HTML-Netflix']
		res = self.testapp.put_json(url, ext_obj, status=200)
		assert_that(res.json_body, has_entries('Items', is_(ext_obj[ITEMS])))
				
		mock_gpi.is_callable().with_args().returns([1,2,3])
		ext_obj[ITEMS] =  [u'tag:nextthought.com,2011-10:CMU-HTML-Bleach']
		self.testapp.put_json(url, ext_obj, status=422)
