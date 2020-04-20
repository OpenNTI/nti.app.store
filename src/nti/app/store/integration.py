#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import interface

from nti.app.products.integration.integration import AbstractIntegration

from nti.app.products.integration.interfaces import IIntegrationCollectionProvider

from nti.app.store.interfaces import IStripeIntegration

from nti.app.store.license_utils import can_integrate

from nti.externalization.representation import WithRepr

from nti.schema.fieldproperty import createDirectFieldProperties

from nti.schema.schema import SchemaConfigured

logger = __import__('logging').getLogger(__name__)


@WithRepr
@interface.implementer(IStripeIntegration)
class StripeIntegration(AbstractIntegration,
                        SchemaConfigured):
    createDirectFieldProperties(IStripeIntegration)

    __external_can_create__ = False

    __name__ = u'stripe'

    mimeType = mime_type = "application/vnd.nextthought.integration.stripeintegration"


@interface.implementer(IIntegrationCollectionProvider)
class StripeIntegrationProvider(object):

    def get_collection_iter(self):
        """
        Return a StripeIntegration object on which we can decorate the
        links for connecting or disconnecting Stripe accounts.
        """
        result = ()
        if can_integrate():
            result = (StripeIntegration(title=u'Integrate with Stripe'),)
        return result
