#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved

Base classes for collecting data.
"""

import copy
import datetime
import json
import logging
import time


class HivearyBaseMonitor(object):
  """Default class for defining a monitor. This does nothing on its own, it should
  be subclassed with at least check_data defined."""

  AGGREGATION_TIMER = 1800  # 30 minutes
  FLOP_PROTECTION_COUNTER = 6
  MONITOR_TIMER = 1
  DEFAULT_ALERT_BACKOFF = 3600  # Delay between similar alerts, in seconds
  NAME = 'base'
  TYPE = None
  SOURCES = []

  def __init__(self, backoff=None, logger=None):
    """Initialize the monitor.

    Args:
      backoff: The amount of time to delay between repeated alerts, in seconds.
      logger: A logging object to use.
    """

    self.logger = logger or logging.getLogger('hiveary_agent.%s' % self.NAME)

    self.backoff = backoff or self.DEFAULT_ALERT_BACKOFF
    self.logger.info('Using an alert backoff of %d seconds', self.backoff)

    self.expected_values = {}
    self.data_points = []

  def store_data_point(self, data):
    """Puts a single data point into the database.

    Args:
      data: A dictionary of any data to be stored.
    """

    monitor_data = copy.copy(data)
    monitor_data['timestamp'] = time.time()
    self.data_points.append(monitor_data)

  def send_data(self, net_controller):
    """Sends the resource usage data points for the past time period.

    Args:
      net_controller: A NetworkController object with an active AMQP connection.
    """

    # Determine how much stored data to send based on the defined monitor periods
    now_dt = datetime.datetime.utcnow()
    earliest = time.time() - datetime.timedelta(minutes=30,
                                                seconds=now_dt.second,
                                                microseconds=now_dt.microsecond).total_seconds()
    seconds = (now_dt - now_dt.min).seconds
    rounding = (seconds + self.AGGREGATION_TIMER/2) // self.AGGREGATION_TIMER * self.AGGREGATION_TIMER
    time_period = now_dt + datetime.timedelta(0, rounding-seconds, -now_dt.microsecond)

    data = defaultdict(list)
    data['period'] = time_period.strftime('%H%M')
    data['day'] = time_period.weekday()
    data['host_id'] = net_controller.obj_id
    data['monitor_name'] = self.NAME

    if self.TYPE == 'usage':
      data['monitor_sources'] = self.SOURCES

    for point in self.data_points:
      # Throw out any data points that are too old
      timestamp = point.pop('timestamp')
      if timestamp >= earliest:
        for resource, value in point.iteritems():
          data[resource].append(value)

    self.logger.debug('Full data since %s: %s', earliest, data)

    # Send the full data up to the server.
    net_controller.publish_info_message(self.TYPE, json.dumps(data))
    self.data_points = []

  def check_data(self):
    """Method for checking the monitored data. This must be defined by a child class.

    Raises:
      NotImplementedError: The method hasn't been overridden in the subclass
                           and will never do anything.
    """

    raise NotImplementedError


class HivearyUsageMonitor(HivearyBaseMonitor):
  """Base class for all "usage" type monitors."""

  TYPE = 'usage'


class HivearyLogMonitor(HivearyBaseMonitor):
  """Base class for all "log" type monitors."""

  TYPE = 'log'


class HivearyStatusMonitor(HivearyBaseMonitor):
  """Base class for all "status" type monitors."""

  TYPE = 'status'


class IntervalMixin(object):
  """Mixin class for handling regular interval-based aggregation -
  i.e. send data exactly on the hour."""

  def next_interval(self, now=None, interval=None):
    """Returns the time in seconds until the next interval.

    Args:
      now: The base-time for determining the next interval.
      interval: Amount of time in between aggreagtion intervals, in seconds.
    Returns:
      An integer indicating the time in seconds until the next interval.
    """

    if now is None:
      now = datetime.datetime.utcnow()
    if interval is None:
      interval = self.AGGREGATION_TIMER

    nsecs_passed = now.minute * 60 + now.second + now.microsecond * 1e-6
    delta = (nsecs_passed // interval) * interval + interval - nsecs_passed

    return delta

