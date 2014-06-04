# -*- coding: utf-8 -*-
"""
$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import re
import six

# item/array functions

def from_delimited(value, delim=' '):
	result = value.split(delim)
	result = re.findall("[^\s]+", value) if len(result) <= 1 else result
	return result

def to_collection(items=None, factory=list, delim=' '):
	result = None
	if not items:
		result = factory()
	elif isinstance(items, factory):
		result = items
	elif isinstance(items, six.string_types):
		result = factory(from_delimited(unicode(items), delim))
	else:
		result = factory(items)
	return result

def to_list(items=None, delim=' '):
	return to_collection(items, list)

def to_frozenset(items=None, delim=' '):
	return to_collection(items, frozenset, delim)

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

true_values = ('1', 'y', 'yes', 't', 'true')
false_values = ('0', 'n', 'no', 'f', 'false')

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
