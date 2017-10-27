#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import six
import time
from datetime import date
from datetime import datetime

from requests.structures import CaseInsensitiveDict

from zope.interface.common.idatetime import IDate
from zope.interface.common.idatetime import IDateTime

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.common.string import is_true
from nti.common.string import is_false

logger = __import__('logging').getLogger(__name__)


class AbstractPostView(AbstractAuthenticatedView,
                       ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        result = super(AbstractPostView, self).readInput(value=value)
        result = CaseInsensitiveDict(result)
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
        return is_true(value) or is_false(value)
    else:
        return False


def to_boolean(value):
    if isinstance(value, bool):
        return value
    if is_true(value):
        return True
    elif is_false(value):
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
