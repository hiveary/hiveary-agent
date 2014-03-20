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

  IMPORTANCE = 5 # How "mission critical" this monitor is on a scale of 1-10
  DATA_INTERVAL = 15 # Time between data collection/send in seconds
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
    self.livestreams = {}

  def send_data(self, net_controller, data):
    """Sends the usage data points for the past time period.

    Args:
      net_controller: A NetworkController object with an active AMQP connection.
    """

    data['host_id'] = net_controller.obj_id
    data['id'] = self.UID

    # Send the full data up to the server.
    net_controller.publish_info_message(self.TYPE, json.dumps(data))

  def run(self):
    """Wrapper call to get the data for monitored sources and check it against
    any set alert values."""

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

  def run(self, net_controller):
    """Wrapper call to get the data for monitored sources and check it against
    any set alert values."""

    data = {
      'timestamp': time.time(),
      'interval': self.DATA_INTERVAL
    }
    data.update(self.get_data())
    self.send_data(net_controller, data)

    # Send a copy of the data to any waiting real-time data streams
    if self.livestreams:
      data.pop('extra', None)
      data_container = {
          'monitor_id': self.UID,
          'data': data,
      }
      for publish in self.livestreams.itervalues():
        publish(data_container)


class ProcessMixin(object):
  """Mixin class for pulling current processes data on alert."""

  PULL_PROCS = True


class UsageMonitor(BaseMonitor):
  """Base class for all "usage" type monitors."""

  TYPE = 'usage'
  SOURCES = {}
  DEFAULT_TYPE = None


class LogMonitor(BaseMonitor):
  """Base class for all "log" type monitors."""

  TYPE = 'log'


class StatusMonitor(BaseMonitor):
  """Base class for all "status" type monitors."""

  TYPE = 'status'
  SOURCES = []
  STATES = []

