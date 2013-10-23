#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved

Hiveary Resource Monitor
Monitors the following sources:
  bytes_sent, bytes_recv, disk, cpu, ram
"""

from collections import defaultdict
import json
import psutil
import time

from hiveary import monitors, sysinfo

class ResourceMonitor(monitors.IntervalMixin, monitors.HivearyUsageMonitor):
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
    source_types = ['percent', 'percent', 'bytes', 'bytes'] + ['percent' for disk in self.disks]
    self.SOURCES = zip(self.resource_list, source_types)
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

