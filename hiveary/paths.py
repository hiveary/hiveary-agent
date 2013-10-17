#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved

Functions for finding and manipulating file paths.
"""

import os
import subprocess
import sys

# Windows specific imports
if subprocess.mswindows:
  from ctypes import c_int, wintypes, windll


CSIDL_COMMON_APPDATA = 35   # Used for finding the path to the config file in Windows


def get_common_appdata_path():
  """Returns the path to the common appdata folder in Windows. Typically this is
  either C:\ProgramData (Vista and higher) or
  C:\Documents and Settings\All Users\Application Data (XP).

  Returns:
    A string of the path to the common appdata folder.
  """

  _SHGetFolderPath = windll.shell32.SHGetFolderPathW
  _SHGetFolderPath.argtypes = [wintypes.HWND,
                               c_int,
                               wintypes.HANDLE,
                               wintypes.DWORD, wintypes.LPCWSTR]

  path_buf = wintypes.create_unicode_buffer(wintypes.MAX_PATH)
  _SHGetFolderPath(0, CSIDL_COMMON_APPDATA, 0, 0, path_buf)

  return path_buf.value


def get_program_path():
  """Returns the agent's directory, even if the agent is frozen.

  Returns:
    A string of the agent's directory.
  """

  if hasattr(sys, 'frozen'):
    resource_dir = os.path.dirname(
        unicode(sys.executable, sys.getfilesystemencoding()))
  else:
    resource_dir = os.path.dirname(
        unicode(__file__, sys.getfilesystemencoding()))

  return os.path.abspath(resource_dir)


def find_executable():
  """Determines the absolute path to the current process's executable and args.

  Returns:
    A tuple with the executable as the first and all args as a list for
    the second item.
  """

  if hasattr(sys, 'frozen'):
    # Figure out the right file to call. When frozen, the running executable will
    # be in a versioned subdirectory of the application.
    app_exe = os.path.basename(sys.executable)
    ver_dir = os.path.dirname(sys.executable)
    app_dir = os.path.dirname(ver_dir)

    # Make sure we aren't already at the root - in some instances there is
    # another directory to transision.
    if os.path.basename(app_dir) == 'appdata':
      app_dir = os.path.dirname(app_dir)

    executable = os.path.join(app_dir, app_exe)
    args = sys.argv[1:]
  else:
    executable = sys.executable
    args = sys.argv

    file_path = os.path.abspath(__file__)
    file_name = os.path.basename(file_path)

    # Check if the agent was invoked with the python command, instead
    # of just being run directly as an executable. If so, make sure that the
    # the absolute path is in the args.
    if file_name in args[0]:
      args[0] = file_path

  return (executable, args)
