#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved
"""


class BaseAlert(object):
  """Base wrapper around the data sent to the server when an alert is fired."""

  def __init__(self, timestamp=None, monitor=None, source=None, event_data=None):
    self.timestamp = timestamp
    self.monitor = monitor
    self.source = source
    self.event_data = event_data or {}


class UsageAlert(BaseAlert):
  """Wrapper around the data sent to the server when a usage alert is fired."""

  def __init__(self, threshold=None, current_usage=None, **kwargs):
    self.threshold = threshold
    self.current_usage = current_usage

    super(UsageAlert, self).__init__(**kwargs)
