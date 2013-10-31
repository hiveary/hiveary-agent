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

import copy
import psutil
import time

from hiveary import monitors, sysinfo


class ResourceMonitor(monitors.PollingMixin, monitors.UsageMonitor):
  """Monitors system resource data."""

  MONITOR_TIMER = 10
  NAME = 'resources'
  UID = '2c72af48-37ce-4ea1-9e53-9f081a6bcb6b'

  def __init__(self, *args, **kwargs):
    # Expected resource usage parameters for the current time frame, stored as percentages
    self.disks = sysinfo.find_valid_disks()

    self.SOURCES = {
        'ram': 'percent',
        'cpu': 'percent',
        'bytes_sent': 'bytes',
        'bytes_recv': 'bytes',
    }
    for disk in self.disks:
      self.SOURCES['disk_' + disk] = 'percent'

    # Initialize the network information
    self.total_net_io = psutil.network_io_counters()
    self.last_check = time.time()

    super(ResourceMonitor, self).__init__(*args, **kwargs)

  def get_data(self):
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
        'cpu': psutil.cpu_percent(interval=None),
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

    # Store the values
    current_usage['extra'] = extra_data
    return current_usage

  def extra_alert_data(self, source, data):
    """Finds additional information that should be sent when an alert is fired
    for this monitor.

    Args:
      source: The source of the fired alert.
      data: A dictionary of information specific to the monitored resources.
    Returns:
      A dictionary containing the additonal information to send with the alert.
    """

    if source == 'ram':
      top = 'memory_percent'
    elif source == 'cpu':
      top = 'cpu_percent'
    else:
      top = None

    procs, top_procs = sysinfo.pull_processes(top=top)
    extra_data = copy.copy(data.get(source, {}))
    extra_data['current_procesess'] = procs

    if top_procs:
      extra_data['top_processes'] = top_procs

    return extra_data
