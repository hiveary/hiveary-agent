#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved

Base classes for collecting data.
"""

import collections
import copy
import datetime
import json
import logging
import time


class BaseMonitor(object):
  """Default class for defining a monitor. This does nothing on its own, it should
  be subclassed with at least get_data defined."""

  AGGREGATION_TIMER = 1800  # 30 minutes
  FLOP_PROTECTION_COUNTER = 6
  MONITOR_TIMER = 1
  DEFAULT_ALERT_BACKOFF = 3600  # Delay between similar alerts, in seconds
  NAME = 'base'
  TYPE = None
  UID = None  # Can be set to any value guaranteed to be unique, a uuid.uuid4() is recommended
  SOURCES = {}

  def __init__(self, backoff=None, logger=None):
    """Initialize the monitor.

    Args:
      backoff: The amount of time to delay between repeated alerts, in seconds.
      logger: A logging object to use.
    Raise:
      AttributeError: The monitor subclass did not set a unique ID.
    """

    self.logger = logger or logging.getLogger('hiveary_agent.%s' % self.NAME)

    if self.UID is None:
      raise AttributeError('UID is not set for monitor %s!' % self.NAME)

    self.logger.info('Monitoring the following sources: %s', self.SOURCES)

    self.backoff = backoff or self.DEFAULT_ALERT_BACKOFF
    self.logger.info('Using an alert backoff of %d seconds', self.backoff)

    self.expected_values = {}
    self.data_points = []

    self.send_alert = None
    self.alert_counters = collections.defaultdict(lambda: 0)
    self.alert_delays = {}
    self.livestreams = {}

    # Store just the source names separately to prevent having to repeatedly
    # look them up
    self.monitored_source_names = set(self.SOURCES.keys())

  def store_data_point(self, data):
    """Puts a single data point into the database.

    Args:
      data: A dictionary of any data to be stored.
    Raises:
      AttributeError: The data reported by the monitor does not match what it
          declared it would be monitoring.
    """

    monitor_data = copy.copy(data)
    monitor_data.pop('extra', None)

    if set(monitor_data.keys()) != self.monitored_source_names:
      raise AttributeError('The returned data does not match the '
                           'source list for monitor %s' % self.NAME)

    monitor_data['timestamp'] = time.time()
    self.data_points.append(monitor_data)

  def merge_data(self, earliest=0):
    """Merges all stored datapoints into a single dictionary.

    Args:
      earliest: Optional, a timestamp (in seconds since the epoch) of the earliest
          time to return data for. If provided, any datapoints recorded before
          earliest will be ignored.
    Returns:
      A dictionary of source: [datapoints]
    """

    data = collections.defaultdict(list)

    for point in self.data_points:
      # Throw out any data points that are too old
      if point['timestamp'] >= earliest:
        for source, value in point.iteritems():
          data[source].append(value)

    return data

  def send_data(self, net_controller):
    """Sends the usage data points for the past time period.

    Args:
      net_controller: A NetworkController object with an active AMQP connection.
    """

    # Determine how much stored data to send based on the defined monitor periods
    now_dt = datetime.datetime.utcnow()
    earliest = time.time() - datetime.timedelta(minutes=30,
                                                seconds=now_dt.second,
                                                microseconds=now_dt.microsecond).total_seconds()
    seconds = (now_dt - now_dt.min).seconds
    rounding = (seconds + self.AGGREGATION_TIMER / 2) // self.AGGREGATION_TIMER * self.AGGREGATION_TIMER
    time_period = now_dt + datetime.timedelta(0, rounding - seconds, -now_dt.microsecond)

    data = self.merge_data(earliest)
    data.pop('timestamp')
    data['period'] = time_period.strftime('%H%M')
    data['day'] = time_period.weekday()
    data['host_id'] = net_controller.obj_id
    data['id'] = self.UID
    data['interval'] = self.MONITOR_TIMER

    self.logger.debug('Full data since %s: %s', earliest, data)

    # Send the full data up to the server.
    net_controller.publish_info_message(self.TYPE, json.dumps(data))
    self.data_points = []

  def run(self):
    """Wrapper call to get the data for monitored sources and check it against
    any set alert values."""

    pass

  def alert_check(self, data):
    """Checks the monitored data to determine if an alert should be created.
    This should be defined by a child class for alerting.

    Args:
      data: A dictionary of the data to check. The keys must match the list of
          monitored sources for the class.
    """

    pass

  def get_data(self):
    """Retrieves the monitored data. This must be defined by a child class.

    Raises:
      NotImplementedError: The method hasn't been overridden in the subclass
                           and will never do anything.
    """

    raise NotImplementedError

  def extra_alert_data(self, source, data):
    """Finds additional information that should be sent when an alert is fired
    for this monitor. This should be defined by a child class.

    Args:
      source: The source of the fired alert.
      data: A dictionary of any additional information generated from the monitor
          while checking its sources.
    """

    pass


class PollingMixin(object):
  """Mixin class for monitors that expect to regularly poll their data sources
  for new data."""

  def run(self):
    """Wrapper call to get the data for monitored sources and check it against
    any set alert values."""

    data = self.get_data()
    self.store_data_point(data)
    self.alert_check(data)

    # Send a copy of the data to any waiting real-time data streams
    if self.livestreams:
      data.pop('extra', None)
      data_container = {
          'monitor_id': self.UID,
          'data': data,
      }
      for publish in self.livestreams.itervalues():
        publish(data_container)


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


class UsageMonitor(IntervalMixin, BaseMonitor):
  """Base class for all "usage" type monitors."""

  TYPE = 'usage'

  def alert_check(self, data):
    """Checks the monitored data to determine if an alert should be created.

    Args:
      data: A dictionary of the data to check. The keys must match the list of
          monitored sources for the class.
    """

    now = time.time()

    for source in self.monitored_source_names:
      delay = self.alert_delays.get(source)
      threshold = self.expected_values.get(source)
      usage = data.get(source)

      if delay and delay <= now:
        self.alert_delays.pop(delay)
        delay = None

      if threshold and not delay and usage >= threshold:
        self.logger.debug('Current %s usage at %s, threshold is %s', source,
                          usage, threshold)

        self.alert_counters[source] += 1
        if self.alert_counters[source] >= self.FLOP_PROTECTION_COUNTER:
          # Send an alert to the server with any extra information for this source
          extra = data.pop('extra', {})
          alert = {
              'threshold': threshold,
              'current_usage': usage,
              'timestamp': now,
              'monitor': {
                  'id': self.UID,
                  'name': self.NAME,
                  'type': self.TYPE,
                  'source': source,
                  'source_type': self.SOURCES[source],
              },
              'event_data': self.extra_alert_data(source, extra) or {},
          }
          self.send_alert(alert)

          # Put a delay on the next alert to prevent a flood of alert messages
          self.alert_delays[source] = now + self.backoff
          self.alert_counters[source]
      else:
        self.alert_counters[source]


class LogMonitor(BaseMonitor):
  """Base class for all "log" type monitors."""

  TYPE = 'log'


class StatusMonitor(BaseMonitor):
  """Base class for all "status" type monitors."""

  TYPE = 'status'
