#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved

Module containing functions related to the Windows COM interface.
"""

import subprocess

# OS specific imports
if subprocess.mswindows:
  import pythoncom
  import win32api
  import win32com.client


# Constants
AUTO_UPDATE_SETTINGS = {
    'InstallationTime': [
        '00:00',
        '01:00',
        '02:00',
        '03:00',
        '04:00',
        '05:00',
        '06:00',
        '07:00',
        '08:00',
        '09:00',
        '10:00',
        '11:00',
        '12:00',
        '13:00',
        '14:00',
        '15:00',
        '16:00',
        '17:00',
        '18:00',
        '19:00',
        '20:00',
        '21:00',
        '22:00',
        '23:00'
      ],
    'InstallationDay': [
        'Every Day',
        'Every Sunday',
        'Every Monday',
        'Every Tuesday',
        'Every Wednesday',
        'Every Thursday',
        'Every Friday',
        'Every Saturday'
      ],
    'NotificationLevel': [
        'Not Configured',
        'Disabled',
        'Notify Before Download',
        'Notify Before Installation',
        'Scheduled Installation'
      ]
  }

WINDOWS_VERSIONS = {
    5: [
        ['', 'Windows 2000 Professional', 'Windows 2000 Server', 'Windows 2000 Server'],
        ['', 'Windows XP', '', ''],
        ['', 'Windows XP 64-bit', 'Windows Server 2003', 'Windows Server 2003'],
      ],
    6: [
        ['', 'Windows Vista', 'Windows Server 2008', 'Windows Server 2008'],
        ['', 'Windows 7', 'Windows Server 2008 R2', 'Windows Server 2008 R2'],
        ['', 'Windows 8', 'Windows Server 2012', 'Windows Server 2012']
      ]
  }


class WindowsCOMClient(object):
  """Class for executing COM commands."""

  def __init__(self, name):
    """Initialize the class.

    Args:
      name: The full dot-separated name of the COM object (ie Excel.Application)
    """

    pythoncom.CoInitialize()
    self.client = win32com.client.Dispatch(name)

  def get_item(self, hierarchy):
    """Retrieve the item as specified by the hierarchy ordering.

    Args:
      hierarchy: A list or dot-separated string of the specific item to retrieve.

    Returns:
      The retrieved COM item.
    """

    if type(hierarchy) == str or type(hierarchy) == unicode:
      hierarchy = hierarchy.split('.')

    item = self.client
    for level in hierarchy:
      item = getattr(item, level)

    return item

  def set_item(self, value, hierarchy):
    """Set the item as specified by the hierarchy ordering to the passed value.

    Args:
      value: The new value for the COM object.
      hierarchy: A list or dot-separated string of the specific item to retrieve.
    """

    if type(hierarchy) == str or type(hierarchy) == unicode:
      hierarchy = hierarchy.split('.')

    item = self.client
    for level in hierarchy[:-1]:
      item = getattr(item, level)

    setattr(item, hierarchy[-1], value)


def get_version_info():
  """Returns the operating system version info.

  Returns:
    A dictionary of the operating system version info. Example:

    {
      'product_name': 'Windows 8',
      'service_pack': 0,
      'version_number': '6.2'
    }
  """

  version_tuple = win32api.GetVersionEx(1)
  # 0 is the major version, 1 is the minor version, and 8 is the product type
  # Product type can be:
  #   1 (VER_NT_WORKSTATION) - workstation
  #   2 (VER_NT_SERVER) - server
  #   3 (VER_NT_DOMAIN_CONTROLLER) - server and domain controller
  version_name = WINDOWS_VERSIONS[version_tuple[0]][version_tuple[1]][version_tuple[8]]

  version_info = {
      'product_name': version_name,
      'version_number': '%s.%s' % version_tuple[:2],
      'service_pack': version_tuple[5]
    }

  return version_info


def get_update_settings():
  """Returns the current settings related to Windows updates.

  Returns:
    A dictionary of the current Windows update settings. Example:

    {
      'service_enabled': True,
      'notification_level': 'Scheduled Installation',
      'installation_schedule': {'day': 'Every Day', 'time': '03:00'}
    }
  """

  auto_client = WindowsCOMClient('Microsoft.Update.AutoUpdate')

  notification_level_code = auto_client.get_item('Settings.NotificationLevel')
  notification_level = AUTO_UPDATE_SETTINGS['NotificationLevel'][notification_level_code]

  settings = {
      'service_enabled': auto_client.get_item('ServiceEnabled'),
      'notification_level': notification_level,
    }

  # Check the auto update frequency if they are enabled
  if notification_level_code == 4:
    # ScheduledInstallationTime is a default and unreliable value on
    # Windows 8 and Server 2012
    settings['installation_schedule'] = {
        'day': AUTO_UPDATE_SETTINGS['InstallationDay'][
            auto_client.get_item('Settings.ScheduledInstallationDay')],
        'time': AUTO_UPDATE_SETTINGS['InstallationTime'][
            auto_client.get_item('Settings.ScheduledInstallationTime')]
      }

  return settings
