#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2014 all rights reserved

Hiveary Process Resource Monitor
Monitors all running processes for expected resource usage:
"""

import psutil
import re

from hiveary import monitors
import hiveary.info.logs


class ProcessResourceMonitor(monitors.PollingMixin, monitors.UsageMonitor):
  """Monitors process resource data."""

  MONITOR_TIME = 30
  NAME = 'processes'
  UID = '7e7ef560-9b88-49fd-b8f2-a7f46315614e'

  def __init__(self, *args, **kwargs):

    self.name_to_pid = {}

    for process in psutil.process_iter():
      self.SOURCES[process.name + "_cpu"] = "percent"
      self.SOURCES[process.name + "_ram"] = "percent"
      self.name_to_pid[process.name] = process.pid

    super(ProcessResourceMonitor, self).__init__(*args, **kwargs)

  def get_data(self):
    """Pulls Ram and CPU data for all running processes.

    Returns:
      A dictionary with keys process_name(_cpu|_ram) to their values.
    """

    data = {}

    for process in psutil.process_iter():
      data[process.name + "_cpu"] = process.get_cpu_percent()
      data[process.name + "_ram"] = process.get_memory_percent()
      self.name_to_pid[process.name] = process.pid

    return data

  def extra_alert_data(self, process_source):
    """Pulls extra information about the process when the alert is fired.

    Args:
      process_source: the process for which the alert is firing.
    Returns:
      A dictionary containing the extra alert information.
    """

    reg = re.compile('(_cpu|_ram)')
    process_name = reg.sub('', process_source)
    pid = self.name_to_pid[process_name]
    extra_data = {}

    try:
      process = psutil.Process(pid)
    except psutil.NoSuchProcess:
      return extra_data
    else:
      for log_file in hiveary.info.logs.log_files(process):
        last_logs = hiveary.info.logs.tail_file(log_file)
        extra_data[log_file] = last_logs

    return extra_data
