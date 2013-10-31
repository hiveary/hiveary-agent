#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved
"""

import atexit
import errno
import os
import platform
import psutil
import signal
import subprocess
import sys
import time

if platform.system() == 'Windows':
  import win32con


class Daemon(object):
  """A generic daemon class, modified from the original.

  Original version: http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/
  License: https://creativecommons.org/licenses/by-sa/3.0/

  Usage: subclass the Daemon class and override the run() method."""

  def __init__(self, pidfile, term_timeout=20,
               stdin=os.devnull, stdout=os.devnull, stderr=os.devnull,
               executable=sys.executable, args=sys.argv):
    self.stdin = stdin
    self.stdout = stdout
    self.stderr = stderr
    self.pidfile = pidfile
    self.term_timeout = term_timeout
    self.exec_params = [executable] + args

  def fork(self, detached=True, exit=True):
    """Do the UNIX double-fork magic, see Stevens' "Advanced
    Programming in the UNIX Environment" for details (ISBN 0201563177)
    http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
    On Windows we can just create a detached subprocess.

    Args:
      detached: Whether the new process should be started completely independantly,
          or hook into the current stdin/stderr/stdout.
      exit: Whether to exit after forking. This should be true unless the process
          will exit somewhere else.
    """

    if platform.system() == 'Windows':
      # Clean out the params so that the forked process starts normally, without
      # trying to daemonize itself again
      if 'start' in self.exec_params:
        self.exec_params.remove('start')
      if 'restart' in self.exec_params:
        self.exec_params.remove('restart')

      if detached:
        proc = subprocess.Popen(self.exec_params,
                                creationflags=win32con.DETACHED_PROCESS,
                                close_fds=True)
      else:
        proc = subprocess.Popen(self.exec_params)

      # write pidfile and exit
      self.write_pid(proc.pid)
      if exit:
        sys.exit()
    else:
      try:
        pid = os.fork()
        if pid > 0:
          # exit first parent
          sys.exit(0)
      except OSError, e:
        sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
        sys.exit(1)

      # decouple from parent environment
      os.chdir("/")
      os.setsid()
      os.umask(0)

      # do second fork
      try:
        pid = os.fork()
        if pid > 0:
          # exit from second parent
          sys.exit(0)
      except OSError, e:
        sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
        sys.exit(1)

      # redirect standard file descriptors
      sys.stdout.flush()
      sys.stderr.flush()
      si = file(self.stdin, 'r')
      so = file(self.stdout, 'a+')
      se = file(self.stderr, 'a+', 0)
      os.dup2(si.fileno(), sys.stdin.fileno())
      os.dup2(so.fileno(), sys.stdout.fileno())
      os.dup2(se.fileno(), sys.stderr.fileno())

      # write pidfile
      atexit.register(self.delpid)
      self.write_pid(str(os.getpid()))

  def delpid(self):
    """Deletes the PID file for the daemon if it exists."""

    if os.path.exists(self.pidfile):
      os.remove(self.pidfile)

  def start(self):
    """Start the daemon."""

    # Check for a pidfile to see if the daemon already runs
    try:
      with open(self.pidfile, 'r') as pf:
        pid = int(pf.read().strip())
    except IOError:
      pid = None

    if pid:
      message = "pidfile %s already exist. Daemon already running?\n"
      sys.stderr.write(message % self.pidfile)
      sys.exit(1)

    # Start the daemon
    self.fork(detached=True, exit=True)
    self.run()

  def stop(self):
    """Stop the daemon."""

    pid = self.get_pid()
    start_time = time.time()
    timeout = start_time + self.term_timeout

    if not pid:
      message = "pidfile %s does not exist. Daemon not running?\n"
      sys.stderr.write(message % self.pidfile)
      return  # not an error in a restart

    # Try gently stopping the daemon, and escalate if it does not exit
    try:
      while time.time() < timeout:
        os.kill(pid, signal.SIGINT)
        time.sleep(0.5)

      if hasattr(signal, 'SIGKILL'):
        os.kill(pid, signal.SIGKILL)
        self.delpid()
      else:
        message = 'Failed to terminate process %s\n' % pid
        sys.stderr.write(message)
        sys.exit(1)
    except OSError, err:
      if err.errno != errno.EPERM and err.errno != errno.EACCES:
        self.delpid()
      else:
        raise

  def get_pid(self):
    """Get the pid from the pidfile."""

    try:
      with open(self.pidfile, 'r') as pf:
        pid = int(pf.read().strip())
    except IOError:
      pid = None

    return pid

  def status(self):
    """Output the status of the daemon."""

    pid = self.get_pid()
    if pid is None:
      message = 'Hiveary Agent is not running\n'
      sys.stdout.write(message)
      sys.exit(1)

    # Check for the existence of a process with the pid
    pid_exists = psutil.pid_exists(pid)
    if not pid_exists:
      message = 'Pidfile contains pid %s, but no running process could be found\n' % pid
      sys.stderr.write(message)
      sys.exit(1)

    message = 'Hiveary Agent is running with pid %s\n' % pid
    sys.stdout.write(message)
    sys.exit()

  def write_pid(self, pid):
    """Updates the pid in the pidfile."""

    with file(self.pidfile, 'w') as pf:
      pf.write('%s\n' % pid)

  def run(self):
    """You should override this method when you subclass Daemon. It will be
    called after the process has been daemonized by start() or restart().

    Raises:
      NotImplementedError: The method hasn't been overridden in the subclass
                           and will never do anything.
    """

    raise NotImplementedError
