#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import time
from datetime import date
from datetime import datetime

from requests.structures import CaseInsensitiveDict

from zope.interface.common.idatetime import IDate
from zope.interface.common.idatetime import IDateTime

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.common.string import TRUE_VALUES as true_values
from nti.common.string import FALSE_VALUES as false_values


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
        value = int(value)
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


def parse_datetime(t, safe=False):
    try:
        result = t
        if t is None:
            result = None
        elif is_valid_timestamp(t):
            result = float(t)
        elif isinstance(t, six.string_types):
            try:
                result = IDateTime(t)
            except Exception:
                result = IDate(t)
            result = time.mktime(result.timetuple())
        elif isinstance(t, (date, datetime)):
            result = time.mktime(t.timetuple())
        return result
    except Exception as e:
        if safe:
            return None
        raise e
