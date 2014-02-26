#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2014 all rights reserved

Hiveary Service Monitor
 Monitor expected services run by sysV.
"""


from hiveary import monitors
import hiveary.info
import subprocess


class SysVServiceStatusMonitor(monitors.PollingMixin, monitors.StatusMonitor):
  """Monitors system services."""

  MONITOR_TIMER = 30
  NAME = 'services'
  UID = '4bf38a86-9ae5-45c4-888e-b5bb0d631443'

  def __init__(self, *args, **kwargs):
    self.STATES = ['started', 'stopped', 'unknown']
    proc = subprocess.Popen(['service', '--status-all'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in proc.stdout.readlines():
      # Line comes in the form of '[ ? ]  acpid'
      parsed_line = line.strip().split()
      self.SOURCES.append(parsed_line[3])

    super(SysVServiceStatusMonitor, self).__init__(*args, **kwargs)

  def get_data(self):
    data = {}
    proc = subprocess.Popen(['service', '--status-all'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in proc.stdout.readlines():
      # Line comes in the form of '[ ? ]  acpid'
      parsed_line = line.strip().split()
      if parsed_line[1] == '+':
        state = 'started'
      elif parsed_line[1] == '-':
        state = 'stopped'
      elif parsed_line[1] == '?':
        state = 'unknown'
      data[parsed_line[3]] = state
    return data
