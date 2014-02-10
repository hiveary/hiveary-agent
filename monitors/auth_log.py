#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2014 all rights reserved

Hiveary Authentication Log Monitor
Monitors the system authentication log.
"""

from hiveary import monitors


class AuthLogMonitor(monitors.LogMonitor):
  """Monitors the system authentication log."""

  NAME = 'auth log'
  UID = 'd8a38489-5e99-4780-8dc5-b3841bb21d58'
  LOG_LOCATIONS = {
      'Linux': '/var/log/auth.log'
  }
