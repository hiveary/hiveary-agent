#!/usr/bin/env python
# coding=utf8

# Copyright (C) 2010 Saúl ibarra Corretgé <saghul@gmail.com>
#
#

"""
Modified from: https://gist.github.com/saghul/542780

Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2014 all rights reserved

pydmesg: dmesg with human-readable timestamps
"""

from __future__ import with_statement

import re
import subprocess
import sys


# Regex for dmesg lines that allows the source of the message to be obtained.
_dmesg_line_regex = re.compile("^\[.*?\] ((?P<source>.*?): )?.*$")


def exec_process(cmdline, silent, input=None, **kwargs):
  """Execute a subprocess and returns the returncode, stdout buffer and stderr buffer.
     Optionally prints stdout and stderr while running."""
  try:
    sub = subprocess.Popen(cmdline, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    stdout, stderr = sub.communicate(input=input)
    returncode = sub.returncode
    if not silent:
      sys.stdout.write(stdout)
      sys.stderr.write(stderr)
  except OSError, e:
    if e.errno == 2:
      raise RuntimeError('"%s" is not present on this system' % cmdline[0])
    else:
      raise
  if returncode != 0:
    raise RuntimeError('Got return value %d while executing "%s", stderr output was:\n%s' % (returncode, " ".join(cmdline), stderr.rstrip("\n")))
  return stdout


def human_dmesg(source=None, max_lines=20):
  """Format and return lines from the output of dmesg.

  Args:
    source: If provided, only lines from this source will be returned.
    max_lines: The maximum number of lines to return, in reverse order.
  Returns:
    None in the event of an error, otherwise an array of the last dmesg lines.
  """

  formatted_dmesg = []

  # Reversing the array shows the newest lines first, to stay consistent
  # with how other logs are presented.
  dmesg_data = exec_process(['dmesg', '-T'], True).split('\n')
  dmesg_data.reverse()
  for line in dmesg_data:
    if not line:
      continue

    if source:
      match = _dmesg_line_regex.match(line)
      if match:
        source_match = match.groupdict('UNKNOWN')['source']
        if source in source_match:
          formatted_dmesg.append(line)
    else:
      formatted_dmesg.append(line)

    if len(formatted_dmesg) >= max_lines:
      break

  return formatted_dmesg


if __name__ == '__main__':
  print human_dmesg()
