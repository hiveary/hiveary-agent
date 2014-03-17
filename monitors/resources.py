#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2013-2014 all rights reserved

Hiveary Resource Monitor
Monitors the following sources:
  bytes_sent, bytes_recv, disk, cpu, ram
"""

import psutil
import time

from hiveary import monitors
import hiveary.info.logs
import hiveary.info.system


class ResourceMonitor(monitors.ProcessMixin, monitors.PollingMixin, monitors.UsageMonitor):
  """Monitors system resource data."""

  MONITOR_TIMER = 10
  NAME = 'resources'
  UID = '2c72af48-37ce-4ea1-9e53-9f081a6bcb6b'

  def __init__(self, *args, **kwargs):
    # Expected resource usage parameters for the current time frame, stored as percentages
    self.disks = hiveary.info.system.find_valid_disks()

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

    current_usage = {
        'bytes_sent': (network_io.bytes_sent - self.total_net_io.bytes_sent) / time_diff,
        'bytes_recv': (network_io.bytes_recv - self.total_net_io.bytes_recv) / time_diff,
        'ram': ram_usage.percent,
        'cpu': psutil.cpu_percent(interval=None),
    }

    # Add in disk usage data
    for disk in self.disks:
      usage = psutil.disk_usage(disk)
      disk_name = 'disk_{}'.format(disk)
      current_usage[disk_name] = usage.percent

    self.last_check = now
    self.total_net_io = network_io

    return current_usage

  def extra_alert_data(self, source):
    """Finds additional information that should be sent when an alert is fired
    for this monitor.

    Args:
      source: The source of the fired alert.
    Returns:
      A list of dictionaries containing section titles and data
    """

    extra_data = []
    top = None

    if source == 'ram':
      top = 'memory_percent'
      ram_usage = psutil.phymem_usage()
      extra_data.append({
        'title': 'Extra RAM Data',
         'data': {
            'total_memory': ram_usage.total,
            'used_memory': ram_usage.used,
            'free_memory': ram_usage.free,
         },
      })
    elif source == 'cpu':
      top = 'cpu_percent'
    elif source.startswith('disk'):
      device_name = source.split('disk_')[1]
      usage = psutil.disk_usage(device_name)
      extra_data.append({
          'title': 'Extra Disk data',
          'data': {
            'disk': device_name,
            'total_space': usage.total,
            'used_space': usage.used,
            'free_space': usage.free,
          }
      })

    if top:
      top_procs = hiveary.info.system.pull_processes(top=top)
      if top_procs:
        # Find out any more information available about these processes and
        # provide those details to the user.
        top_procs_extra = []
        for process in top_procs:
          # Pull out just a subset of information
          proc_subset = {
              'name': process['name'],
              'pid': process['pid'],
              top: process[top],
              'logs': {},
          }

          # Read any available log information
          for log_file in hiveary.info.logs.log_files(process):
            last_logs = hiveary.info.logs.tail_file(log_file)
            proc_subset['logs'][log_file] = last_logs

          # Remove log subsection if logs not available
          if not proc_subset['logs']:
            proc_subset.pop('logs')
          top_procs_extra.append(proc_subset)

        extra_data.append({
          'title': 'Top processes by {} usage'.format(source),
          'data': top_procs_extra,
        })

    system_logs = hiveary.info.logs.read_system_logs()
    if system_logs:
      extra_data.append({
        'title': 'System logs',
        'data': system_logs,
      })

    return extra_data
