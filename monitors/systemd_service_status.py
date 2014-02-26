#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2014 all rights reserved

Hiveary Systemd Service Monitor
  Monitors the status of all services run by systemd
"""


from hiveary import monitors
import hiveary.info
import subprocess


class SystemdServiceStatusMonitor(monitors.PollingMixin, monitors.StatusMonitor):
  """Monitors system services."""

  MONITOR_TIMER = 30
  NAME = 'services'
  UID = 'cfdf70a7-d007-4dd6-9840-b390fcb340e6'

  def __init__(self, *args, **kwargs):
    self.STATES = ['active', 'inactive', 'failed']
    proc = subprocess.Popen(['systemctl', 'list-units', '-t', 'service', '--all', '--no-legend'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    self.service_manager = 'systemd'
    for line in proc.stdout.readlines():
      # Line output is "procname, load, active, sub, description"
      line = line.strip().split()
      # The description can have spaces, so we reconstruct it into one entry
      parsed_line = line[:4] + [" ".join(line[4:])]
      self.SOURCES.append(parsed_line[0])

    super(SystemdServiceStatusMonitor, self).__init__(*args, **kwargs)

  def get_data(self):
    data = {}
    proc = subprocess.Popen(['systemctl', 'list-units', '-t', 'service', '--all', '--no-legend'], stdout=subprocess.PIPE)
    for line in proc.stdout.readlines():
      # Line output is "procname, load, active, sub, description"
      line = line.strip().split()
      # The description can have spaces, so we reconstruct it into one entry
      parsed_line = line[:4] + [" ".join(line[4:])]
      data[parsed_line[0]] = parsed_line[2]
    return data
