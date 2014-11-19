#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.utils.maps import CaseInsensitiveDict

true_values = ('1', 'y', 'yes', 't', 'true')
false_values = ('0', 'n', 'no', 'f', 'false')

class AbstractPostView(AbstractAuthenticatedView,
					   ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		result = CaseInsensitiveDict()
		if self.request.body:
			values = super(AbstractPostView, self).readInput(value=value)
			result.update(values)
		return result

def is_valid_timestamp(ts):
	try:
		ts = float(ts)
		return ts >= 0
	except (TypeError, ValueError):
		return False

def is_valid_amount(amount):
	try:
		amount = float(amount)
		return amount >= 0
	except (TypeError, ValueError):
		return False

def is_valid_pve_int(value):
	try:
		value = float(value)
		return value > 0
	except (TypeError, ValueError):
		return False

def is_valid_boolean(value):
	if isinstance(value, bool):
		return True
	elif isinstance(value, six.string_types):
		v = value.lower()
		return v in true_values or v in false_values
	else:
		return False

def to_boolean(value):
	if isinstance(value, bool):
		return value
	v = value.lower() if isinstance(value, six.string_types) else value
	if v in true_values:
		return True
	elif v in false_values:
		return False
	else:
		return None

def is_true(value):
	value = value if isinstance(value, six.string_types) else str(value)
	return value.lower() in true_values

def safestr(s):
	s = s.decode("utf-8") if isinstance(s, bytes) else s
	return unicode(s) if s is not None else None
