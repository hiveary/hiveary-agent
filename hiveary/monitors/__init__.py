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
import shlex
import subprocess
import time

import hiveary.info.system


class BaseMonitor(object):
  """Default class for defining a monitor. This does nothing on its own, it should
  be subclassed with at least get_data defined."""

  AGGREGATION_TIMER = 1800  # 30 minutes
  IMPORTANCE = 5 # How "mission critical" this monitor is on a scale of 1-10
  FLOP_PROTECTION_COUNTER = 6
  MONITOR_TIMER = 1
  NAME = 'base'
  TYPE = None
  UID = None  # Can be set to any value guaranteed to be unique, a uuid.uuid4() is recommended
  SOURCES = None
  PULL_PROCS = False
  SERVICES = None

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

    self.expected_values = {}
    self.data_points = []

    self.send_alert = None
    self.failing_alert_counters = collections.defaultdict(lambda: 0)
    self.passing_alert_counters = collections.defaultdict(lambda: 0)
    self.alert_status = collections.defaultdict(lambda: False)
    self.livestreams = {}

  def store_data_point(self, data):
    """Puts a single data point into the database.

    Args:
      data: A dictionary of any data to be stored.
    Raises:
      AttributeError: The data reported by the monitor does not match what it
          declared it would be monitoring.
    """

    monitor_data = copy.copy(data)
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

  def extra_alert_data(self, source):
    """Finds additional information that should be sent when an alert is fired
    for this monitor. This should be defined by a child class.

    Args:
      source: The source of the fired alert.
    """

    pass


class ExternalMonitor(BaseMonitor):
  """Class used to load an external monitor with an external data pull."""

  def __init__(self, *args, **kwargs):
    self.UID = kwargs.pop('uid')
    # We have to call super after setting the UID as BaseMonitor expects a UID.
    # We need to call base monitor first, for the logger from the get data command.
    super(ExternalMonitor, self).__init__()

    self.SERVICES = kwargs.pop('services', None)
    # Clamp importance to between 1-10 with default 5
    self.IMPORTANCE = max(1, min(kwargs.pop('importance', 5), 10))
    self.NAME = kwargs.pop('name')
    self.get_data_command = shlex.split(kwargs.pop('get_data'))
    self.extra_data_command = shlex.split(kwargs.pop('extra_data', ''))

    monitor_type = kwargs.pop('type').lower()
    sources = kwargs.pop('sources', None)
    default_type = kwargs.pop('default_type', '')
    states = kwargs.pop('states', None)

    # Monitor type specific instantiation
    if monitor_type == 'usage':
      if not sources:
        sources = {}
        for source in self.get_data().keys():
          sources[source] = default_type
      if sources and type(sources) is not dict:
        raise TypeError('Sources for usage monitor is not a dict')
      self.DEFAULT_TYPE = default_type

    elif monitor_type == 'status':
      if not sources:
        sources = self.get_data().keys()
      if sources and type(sources) is not list:
        raise TypeError('Sources for status monitor is not a list')
      if type(states) is not list:
        raise TypeError('States for status monitor is not a list')
      self.STATES = states

    self.SOURCES = sources

    # Load in any other overrides provided
    for key, value in kwargs.iteritems():
      if hasattr(self, key):
        setattr(self, key, value)
    self.logger.info('Monitoring the following sources: %s', self.SOURCES)

  def get_data(self):
    data = {}
    try:
      proc = subprocess.Popen(self.get_data_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
      data = json.loads(proc.communicate()[0])
    except ValueError as e:
      self.logger.warn('Failed to parse get_data output for %s monitor', self.NAME)
    except:
      self.logger.error('Get data failed for %s monitor', self.NAME, exc_info=True)

    if type(data) is not dict:
      self.logger.warn('Get data output was not a dictionary for %s monitor, removing data', self.NAME)
      data = {}
    return data

  def extra_alert_data(self):
    data = {}
    if self.extra_data_command:
      try:
        proc = subprocess.Popen(self.extra_data_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        data = json.loads(proc.communicate()[0])
      except ValueError as e:
        self.logger.debug('Failed to parse extra_data output for %s monitor', self.NAME)
      except:
        self.logger.error('Extra data failed for %s monitor', self.NAME, exc_info=True)
      if type(data) is not dict:
        self.logger.warn('Get extra alert data output was not a dictionary for %s monitor, removing data', self.NAME)
        data = {}
    return data


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


class ProcessMixin(object):
  """Mixin class for pulling current processes data on alert."""

  PULL_PROCS = True


class UsageMonitor(IntervalMixin, BaseMonitor):
  """Base class for all "usage" type monitors."""

  TYPE = 'usage'
  MONITOR_TIMER = 30
  SOURCES = {}
  DEFAULT_TYPE = None

  def alert_check(self, data):
    """Checks the monitored data to determine if an alert should be created.

    Args:
      data: A dictionary of the data to check. The keys must match the list of
          monitored sources for the class.
    """

    now = time.time()

    for source in self.SOURCES.keys():
      threshold = self.expected_values.get(source)
      usage = data.get(source)
      source_is_failing = self.alert_status.get(source)
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
      }

      # Handle case where source status is currently passing, and threshold is exceeded
      if threshold and usage >= threshold and not source_is_failing:
        self.logger.debug('Current %s usage at %s, threshold is %s, trending towards fail', source,
                          usage, threshold)

        self.failing_alert_counters[source] += 1
        if self.failing_alert_counters[source] >= self.FLOP_PROTECTION_COUNTER:
          # Send an alert to the server with any extra information for this source
          alert['event_data'] = self.extra_alert_data(source),
          alert['failing'] = self.alert_status[source] = True
          if self.PULL_PROCS:
            procs = hiveary.info.system.pull_processes()
            alert['current_processes'] = procs

          self.send_alert(alert)
          self.failing_alert_counters[source] = 0

      # Handle case where source status is currently passing and threshold is not exceeded
      elif threshold and usage < threshold and source_is_failing:
        self.logger.debug('Current %s usage at %s, threshold is %s, trending towards pass', source,
                          usage, threshold)
        self.passing_alert_counters[source] += 1
        if self.passing_alert_counters[source] >= self.FLOP_PROTECTION_COUNTER:
          alert['failing'] = self.alert_status[source] = False
          self.send_alert(alert)
          self.passing_alert_counters[source] = 0
      else:
        # No potential change, reset all counters
        self.passing_alert_counters[source] = self.failing_alert_counters[source] = 0


class LogMonitor(BaseMonitor):
  """Base class for all "log" type monitors."""

  TYPE = 'log'


class StatusMonitor(IntervalMixin, BaseMonitor):
  """Base class for all "status" type monitors."""

  TYPE = 'status'
  STATES = []
  SOURCES = []

  def alert_check(self, data):
    """Checks to see if the monitored sources are in the expected state.

    Args:
      data: dictonary of source to its state.
    """

    now = time.time()

    for source in self.SOURCES:
      expected_state = self.expected_values.get(source)
      current_state = data.get(source)
      alert = {
          'expected_state': expected_state,
          'current_state': current_state,
          'timestamp': now,
          'monitor': {
              'id': self.UID,
              'name': self.NAME,
              'type': self.TYPE,
              'source': source,
          },
      }
      source_is_failing = self.alert_status.get(source)

      if not source_is_failing and expected_state and expected_state != current_state:
        self.logger.debug('Current %s state is %s, expected state is %s, check failing', source,
                          current_state, expected_state)

        alert['failing'] = True
        alert['event_data'] = self.extra_alert_data(source),
        self.send_alert(alert)

      elif source_is_failing and expected_state and expected_state == current_state:
        self.logger.debug('Current %s state is %s, expected state is %s, check passing', source,
                          current_state, expected_state)
        alert['failing'] = False
        self.send_alert(alert)
