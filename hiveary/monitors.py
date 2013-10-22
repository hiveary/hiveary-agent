#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved

Base classes for collecting data.
"""

from collections import defaultdict
import copy
import datetime
import json
import logging
import psutil
import time

# Local imports
from . import sysinfo


class BaseMonitor(object):
  """Default class for defining a monitor. This does nothing on its own, it should
  be subclassed with at least check_data defined."""

  AGGREGATION_TIMER = 1800  # 30 minutes
  FLOP_PROTECTION_COUNTER = 6
  MONITOR_TIMER = 1
  DEFAULT_ALERT_BACKOFF = 3600  # Delay between similar alerts, in seconds
  NAME = 'base'

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

    usage = copy.copy(data)
    usage['timestamp'] = time.time()
    self.data_points.append(usage)

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

    for point in self.data_points:
      # Throw out any data points that are too old
      timestamp = point.pop('timestamp')
      if timestamp >= earliest:
        for resource, value in point.iteritems():
          data[resource].append(value)

    self.logger.debug('Full data since %s: %s', earliest, data)

    # Send the full data up to the server.
    net_controller.publish_info_message('resource_usage', json.dumps(data))
    self.data_points = []

  def check_data(self):
    """Method for checking the monitored data. This must be defined by a child class.

    Raises:
      NotImplementedError: The method hasn't been overridden in the subclass
                           and will never do anything.
    """

    raise NotImplementedError


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


class ResourceMonitor(IntervalMixin, BaseMonitor):
  """Monitors system resource data."""

  MONITOR_TIMER = 10
  NAME = 'resources'

  def __init__(self, *args, **kwargs):
    super(ResourceMonitor, self).__init__(*args, **kwargs)

    # Expected resource usage parameters for the current time frame, stored as percentages
    self.alert_counters = defaultdict(lambda: 0)
    self.alert_delays = {}
    self.resource_list = ['ram', 'cpu', 'bytes_sent', 'bytes_recv']
    self.disks = sysinfo.find_valid_disks()
    self.resource_list.extend(self.disks)

    self.logger.info('Monitoring the following resources: %s', self.resource_list)

    # Initialize the network information
    self.total_net_io = psutil.network_io_counters()
    self.last_check = time.time()

  def check_data(self):
    """Gets the system's resource usage and sends an alert when it becomes too high."""

    now = time.time()

    # We have to aggregate usage so we'll pull everything regardless of the params
    network_io = psutil.network_io_counters()
    time_diff = now - self.last_check
    ram_usage = psutil.phymem_usage()
    disk_usage = {}
    for disk in self.disks:
      disk_usage[disk] = psutil.disk_usage(disk)

    current_usage = {
        'bytes_sent': (network_io.bytes_sent - self.total_net_io.bytes_sent) / time_diff,
        'bytes_recv': (network_io.bytes_recv - self.total_net_io.bytes_recv) / time_diff,
        'ram': ram_usage.percent,
        'cpu': psutil.cpu_percent(),
    }

    extra_data = {
        'ram': {
            'total_memory': ram_usage.total,
            'used_memory': ram_usage.used,
            'free_memory': ram_usage.free,
            'resource': 'RAM',
        },
        'cpu': {
            'resource': 'CPU',
        }
    }

    # Add in disk usage data
    for device, usage in disk_usage.iteritems():
      disk_name = 'disk_%s' % device
      current_usage[disk_name] = usage.percent
      extra_data[disk_name] = {
          'disk': device,
          'total_space': usage.total,
          'used_space': usage.used,
          'free_space': usage.free,
      }

    self.last_check = now
    self.total_net_io = network_io

    # Store the values in our sqllite DB
    self.store_data_point(current_usage)

    for resource in self.resource_list:
      delay = self.alert_delays.get(resource)
      threshold = self.expected_values.get(resource)
      usage = current_usage.get(resource)

      if delay and delay <= now:
        self.alert_delays.pop(delay)
        delay = None

      if threshold and not delay and usage >= threshold:
        self.logger.debug('Current %s usage at %s, threshold is %s', resource,
                          usage, threshold)

        self.alert_counters[resource] += 1
        if self.alert_counters[resource] >= self.FLOP_PROTECTION_COUNTER:
          # Send an alert to the server
          data = {
              'threshold': threshold,
              'current_usage': usage,
              'host_id': self.obj_id,
              'current_procesess': sysinfo.pull_processes(),
              'resource': resource,
              'timestamp': now,
          }

          # Add in any extra information for this resource and send it off
          data.update(extra_data.get(resource, {}))
          self.network_controller.publish_info_message('alert', json.dumps(data))

          # Put a delay on the next alert to prevent a flood of alert messages
          self.alert_delays[resource] = now + self.backoff
          self.alert_counters[resource]
      else:
        self.alert_counters[resource]

