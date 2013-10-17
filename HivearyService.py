#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved
"""

import os.path
import servicemanager
import subprocess
import sys
import thread
import win32serviceutil
import win32service
import win32event


class ServiceEvent(object):
  """Event class which permits synchronization between threads."""

  def __init__(self):
    self.lock = thread.allocate_lock()
    self.isSet = False
    self.waiters = []

  def set(self):
    """Set the flag and notify all waiters of the event."""

    self.lock.acquire()
    self.isSet = True
    if self.waiters:
      for waiter in self.waiters:
        waiter.release()
      self.waiters = []
      self.isSet = False
    self.lock.release()

  def wait(self, handler):
    """Wait for the flag to be set and immediately reset it.

    Args:
      handler: A reference to the object as a service.
    """

    self.lock.acquire()
    if self.isSet:
      self.isSet = False
      self.lock.release()
    else:
      waiterLock = thread.allocate_lock()
      with waiterLock:
        self.waiters.append(waiterLock)
        self.lock.release()
        while waiterLock.locked():
          # Poll returns None if the process is running and a numeric exit code otherwise
          if handler.agent.poll():
            servicemanager.LogErrorMsg('Agent unexpectedly terminated, restarting')
            handler.SvcDoRun()
        waiterLock.acquire()


class HivearyService(win32serviceutil.ServiceFramework):
  """Class for being a Windows service."""

  _svc_name_ = "HivearyService"
  _svc_display_name_ = "Hiveary Agent"

  def __init__(self, args):
    win32serviceutil.ServiceFramework.__init__(self, args)

    servicemanager.LogInfoMsg('Creating service instance')
    self.stopEvent = ServiceEvent()
    self.agent = None
    self.agent_executable = os.path.join(os.path.dirname(sys.executable),
                                         'hiveary-agent.exe')

    self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)

  def SvcStop(self):
    """Called when the service is being stopped."""

    self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
    servicemanager.LogInfoMsg('Stopping service')
    if self.agent:
      try:
        self.agent.terminate()
      except WindowsError, error:
        servicemanager.LogErrorMsg('Error terminating the agent: %s' % error)
      servicemanager.LogInfoMsg('Agent terminated')

    self.stopEvent.set()
    win32event.SetEvent(self.hWaitStop)

  def SvcDoRun(self):
    """Called when the service starts up."""

    servicemanager.LogInfoMsg('Running service...starting agent at %s' % self.agent_executable)
    self.agent = subprocess.Popen([self.agent_executable])
    self.stopEvent.wait(self)


if __name__ == '__main__':
  win32serviceutil.HandleCommandLine(HivearyService)
