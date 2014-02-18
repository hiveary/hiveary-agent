#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2014 all rights reserved

Hiveary Windows Service Monitor
  Monitor windows service statuses
"""

import win32service

from hiveary import monitors
import hiveary.info


class WindowsServiceStatusMonitor(monitors.PollingMixin, monitors.StatusMonitor):
  """Monitors system services."""

  MONITOR_TIMER = 30
  NAME = 'services'
  UID = '7a80474c-4d94-4b43-9162-a639b0326377'

  def __init__(self, *args, **kwargs):
    self.STATES = ['STOPPED', 'RUNNING', 'PAUSED']
    # Create and SC Mager to query the SCM Database
    access = win32service.SC_MANAGER_ENUMERATE_SERVICE
    self.scmanager = win32service.OpenSCManager(None, None, access)
    services = get_windows_services()
    for (name, desc, status) in services:
      self.SOURCES.append(name)

    super(WindowsServiceStatusMonitor, self).__init__(*args, **kwargs)

  def get_data(self):
    data = {}
    if hiveary.info.current_system == 'Windows':
      services = get_windows_services()
      for (name, desc, status) in services:
        # status object is a tuple of service type, current status,
        # controls accepted and.. other stuff?
        status = status[1]
        if status == win32service.SERVICE_RUNNING:
          data[name] = 'RUNNING'
        elif (status == win32service.SERVICE_STOPPED or
              status == win32service.SERVICE_STOP_PENDING or
              status == win32service.SERVICE_CONTINUE_PENDING):
          data[name] = 'STOPPED'
        elif (status == win32service.SERVICE_PAUSE_PENDING or
              status == win32service.SERVICE_PAUSE or
              status == win32service.SERVICE_CONTINUE_PENDING):
          data[name] = 'PAUSED'
    return data

  def get_windows_services(self):
    """Helper function to pull list of windows services.

    Returns:
      A tuple of http://msdn.microsoft.com/en-us/library/windows/desktop/ms685996(v=vs.85).aspx
    """

    # Query for all services in all states
    typeFilter = win32service.SERVICE_WIN32
    stateFilter = win32service.SERVICE_STATE_ALL
    return win32service.EnumServicesStatus(self.scmanager, typeFilter, stateFilter)
