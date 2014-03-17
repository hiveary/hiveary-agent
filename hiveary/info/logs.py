#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2014 all rights reserved

Functions for collecting local log information.
"""

import datetime
import logging
import os
import subprocess

if subprocess.mswindows:
  import win32evtlog
  import win32evtlogutil
  import win32con
  import winerror
else:
  import hiveary.info.dmesg

import hiveary.info

NUM_LOG_LINES = 20
logger = logging.getLogger('hiveary_agent.info.logs')


def log_files(process, fuzzy_matches=None):
  """Finds the log file being used by the passed process.

  Args:
    process: A psutil.Process instance in dict form.
    fuzzy_matches: An optional iterable of strings to compare against the
        process's open files.
  Returns:
    The full path to the process's log file, or None if it could not
    be determined.
  """

  fuzzy_matches = fuzzy_matches or ('log', 'err', 'info')
  log_paths = []

  for open_file in process.get('open_files', []):
    path = open_file['path']

    # Ignore duplicated file handlers.
    if path in log_paths:
      continue

    # Ignore any binary files.
    if 'text' not in subprocess.check_output(['file', '-b', path]):
      continue

    # Anything within a log directory can be included, regardless of name
    if '/log/' in path:
      log_paths.append(path)
      continue

    filename = os.path.basename(path)

    for fuzzy_match in fuzzy_matches:
      if fuzzy_match in filename:
        log_paths.append(path)
        break

  return log_paths


def tail_file(filename, num_lines=NUM_LOG_LINES):
  """Pulls the last lines from a file.

  Args:
    filename: The name of the file to pull from.
    num_lines: The number of lines to read from the end of the file.
  Returns:
    A string of the lines from the file, or None.
  """

  try:
    # stderr is piped to stdout so that if an error occurs it isn't
    # propogated up to the parent process.
    file_lines = subprocess.check_output(['tail', '-n', str(num_lines), filename],
                                         stderr=subprocess.STDOUT)
  except subprocess.CalledProcessError as err:
    logger.error('Unable to read %s - returned %d: %s',
                 filename, err.returncode, err.message)
  else:
    return file_lines


def read_event_log(logtype='Application', max_entries=NUM_LOG_LINES, hours_back=12):
  """Reads events from the Windows event log.

  Args:
    logtype: The event log to read. One of System, Security, Application.
    max_entries: The maximum number of entries to return from the event log.
    hours_back: How many hours to go back into the logs. Events older than this
        will not be returned.
  Returns:
    An array of recent events from the event log.
  """

  try:
    handle = win32evtlog.OpenEventLog('127.0.0.1', logtype)
  except win32evtlog.error:
    logger.error('Unable to access the %s event log', logtype, exc_info=True)
    return

  # This dict converts the event type into a human readable form. Taken from:
  # http://timgolden.me.uk/pywin32-docs/Windows_NT_Eventlog.html
  evt_types = {
      win32con.EVENTLOG_AUDIT_FAILURE: 'AUDIT_FAILURE',
      win32con.EVENTLOG_AUDIT_SUCCESS: 'AUDIT_SUCCESS',
      win32con.EVENTLOG_INFORMATION_TYPE: 'INFORMATION',
      win32con.EVENTLOG_WARNING_TYPE: 'WARNING',
      win32con.EVENTLOG_ERROR_TYPE: 'ERROR',
  }
  flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ

  relevant_events = []
  oldest = datetime.datetime.now() - datetime.timedelta(hours=hours_back)

  while True:
    events = win32evtlog.ReadEventLog(handle, flags, 0)
    if not events:
      break

    for event in events:
      # Limit the total amount of messages retrieved.
      if len(relevant_events) >= max_entries:
        return relevant_events

      # Only send recent events as events that are too old are unlikely to be
      # useful.
      time_gen = datetime.datetime.strptime(str(event.TimeGenerated),
                                            '%m/%d/%y %H:%M:%S')
      if time_gen < oldest:
        return relevant_events

      formatted_event = {
          'Event ID': winerror.HRESULT_CODE(event.EventID),
          'Time': event.TimeGenerated.Format(),
          'Source': str(event.SourceName),
          'Message': win32evtlogutil.SafeFormatMessage(event, logtype),
          'Type': evt_types.get(event.EventType),
      }
      relevant_events.append(formatted_event)

  return relevant_events


def read_syslog(num_lines=NUM_LOG_LINES):
  """Reads the last lines that were sent to syslog.

  Returns:
    An array of lines from the end of the syslog file, or None.
  """

  possible_syslog_files = ('/var/log/syslog', '/var/log/messages')

  for filename in possible_syslog_files:
    if os.path.isfile(filename):
      break
  else:
    logger.info('A syslog file could not be found on this system.')
    return

  syslog_lines = tail_file(filename)
  if syslog_lines:
    syslog_lines = syslog_lines.strip().split('\n')
    syslog_lines.reverse()
    return syslog_lines


def read_system_logs():
  """Platform-agnostic function for reading the most recent log records from the
  system.

  Returns:
    A dictionary mapping the name or path of the system log to its most recent
    entries.
  """

  system_logs = {}

  if hiveary.info.current_system == 'Windows':
    for event_log_source in ('Application', 'System', 'Security'):
      system_logs[event_log_source] = read_event_log(logtype=event_log_source)
  elif hiveary.info.current_system == 'Linux':
    dmesg_lines = hiveary.info.dmesg.human_dmesg()
    if dmesg_lines:
      system_logs['dmesg'] = dmesg_lines

    syslog_lines = read_syslog()
    if syslog_lines:
      system_logs['syslog'] = syslog_lines

  return [system_logs]
