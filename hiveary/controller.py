#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved
"""

import json
import logging
import os
import signal
import socket
import sys
from twisted.internet import reactor, task

# esky is only needed for updating the application if its frozen
if hasattr(sys, 'frozen'):
  import esky

# Local imports
from . import daemon
from . import monitors
from . import network
from . import paths
from . import sysinfo


class RealityAuditor(daemon.Daemon):
  """Daemon subclass. Makes sure that data is being collected and aggregated,
  network connections are active, and gravity is working."""

  INITIAL_DELAY = 5  # Small delay to make sure the network has been initialized
  UPDATE_TIMER = 60 * 60 * 8  # How often to check for agent updates, in seconds
  PID_FILE = '/var/run/hiveary-agent.pid'  # Default location of the PID file
  REMOTE_HOST = 'hiveary.com'  # Default server to connect to

  def __init__(self, parsed_args, stored_config, logger=None):
    """Initialization when the agent is started.

    Args:
      parsed_args: A dictionary version of the parsed command line arguments.
      stored_config: A dictionary of any values from the config file.
      logger: Optional, the logger that this class should log to.
    """

    # Check that the directory for the pid file exists, and if not then use
    # the same directory as the config file
    pid_file = stored_config.get('pid_file', self.PID_FILE)
    if not os.path.isdir(os.path.dirname(pid_file)):
      directory = os.path.dirname(stored_config['filename'])
      filename = os.path.basename(pid_file)
      pid_file = os.path.join(directory, filename)

    self.logger = logger or logging.getLogger('hiveary_agent.controller')

    # Get and possibly save optional configuration parameters. If the defaults
    # are used, they won't be saved.
    self.extra_options = {}
    for option in ('monitor_backoff', 'pid_file', 'ca_bundle'):
      value = stored_config.get(option)
      if value:
        self.extra_options[option] = value

    # Network controller is initalized by the agent with the necessary
    # authentication credentials
    self.network_controller = network.NetworkController(reactor)
    self.set_config(parsed_args, stored_config)

    # Setup a handler to interpret interrupts since twisted overrides them
    signal.signal(signal.SIGINT, self.signal_handler)

    executable, args = paths.find_executable()
    self.logger.debug('Setting daemon to use %s %s', executable, args)
    super(RealityAuditor, self).__init__(pid_file, executable=executable,
                                         args=args)

  def run(self):
    """Called once the agent has been daemonized, or if the agent is running
    in the foreground. All monitors are started from here and communication
    with the server is started."""

    if hasattr(sys, 'frozen'):
      # Setup the auto-updater
      update_path = 'https://{host}/versions'.format(host=self.REMOTE_HOST)
      reactor.callLater(0, self.start_loop, self.UPDATE_TIMER, True,
                        self.auto_agent_update, update_path)

    # Connect to the server
    self.network_controller.initialize_amqp()

    # Send the first data dump
    data = sysinfo.pull_all()
    data['host_id'] = self.network_controller.obj_id
    reactor.callLater(self.INITIAL_DELAY,
                      self.network_controller.publish_info_message,
                      'startup',
                      json.dumps(data))

    # Send a ping to the server to act as a keep-alive.
    reactor.callLater(self.INITIAL_DELAY, self.start_loop,
                      self.network_controller.PING_TIMER, True,
                      self.network_controller.ping_pong)

    # Setup the resource monitoring loops
    monitor = monitors.ResourceMonitor(backoff=self.extra_options.get('monitor_backoff'))
    self.logger.debug('Starting %s monitor data checks', monitor.NAME)
    self.network_controller.expected_values[monitor.NAME] = monitor.expected_values
    self.start_loop(monitor.MONITOR_TIMER, False, monitor.check_data)

    self.start_aggregation_loop(monitor)

    reactor.run()

  def signal_handler(self, signum, stackframe):
    """Handles a SIGTERM or SIGINT sent to the process.

    Args:
      signum: The number of the signal. SIGINT is 2, SIGTERM is 15.
      stackframe: The interrupted stack frame.
    """

    self.logger.info("Received signal: %s", signum)

    # Mark the code as stopping and give timed loops a chance to gracefully close
    self.network_controller.running = False
    if self.network_controller.amqp:
      self.network_controller.amqp.release()
    reactor.callFromThread(reactor.stop)  # Stop twisted code when in the reactor loop

    # Clean up the daemon after the reactor is done
    reactor.addSystemEventTrigger('after', 'shutdown', self.delpid)

  def set_config(self, args, stored_config):
    """Update any configuration variables. Use passed command-line values first,
    then stored config values, then defaults.

    Args:
      args: A dictionary version of the parsed command line arguments.
      stored_config: A dictionary of any values from the config file.
    """

    stored_config.update((k, v) for k, v in args.iteritems() if v is not None)
    self.logger.debug('Using the merged config: %s', stored_config)

    # Store the required network config values in the network controller
    self.network_controller.debug_mode = stored_config['debug']
    self.network_controller.disable_ssl_verification = stored_config['disable_ssl_verify']
    self.network_controller.hostname = socket.getfqdn()
    self.network_controller.owner = stored_config.get('username')
    self.network_controller.access_token = stored_config.get('access_token')
    self.network_controller.remote_host = stored_config.get('server') or self.REMOTE_HOST
    self.network_controller.amqp_server = stored_config.get('amqp_server') or 'amqp.{domain}'.format(
        domain=self.network_controller.remote_host)
    self.network_controller.ca_bundle = stored_config.get('ca_bundle')

    # Update the config file if needed
    if args.update:
      self.update_config_file(stored_config['filename'])

  def update_config_file(self, filename):
    """Stores the current configuration in the config file, overwriting current
    values.

    Args:
      filename: The full path to the config file.
    """

    config = {
        'server': self.network_controller.remote_host,
        'access_token': self.network_controller.access_token,
        'username': self.network_controller.owner,
        'amqp_server': self.network_controller.amqp_server,
    }

    config.update(self.extra_options)

    with open(filename, 'w') as file_desc:
      json.dump(config, file_desc, indent=2)

  def start_aggregation_loop(self, monitor):
    """Starts the aggregation loop, setting it up to use the exact intervals
    if the passed monitor uses intervals.

    Args:
      monitor: The monitor object. Must be a subclass of BaseMonitor.
    """

    if hasattr(monitor, 'next_interval'):
      # Only start aggregating data at a specified time to make sure that we
      # maintain the same time intervals. The first run will contain a partial
      # period if we have data points from at least half that period.
      delta = monitor.next_interval()
      self.logger.debug('Starting %s aggregation loop in %s seconds', monitor.NAME, delta)
      start_now = delta > (monitor.AGGREGATION_TIMER / 2)
    else:
      delta = monitor.AGGREGATION_TIMER
      start_now = True

    reactor.callLater(int(delta), self.start_loop,
                      monitor.AGGREGATION_TIMER, start_now,
                      monitor.send_data, self.network_controller)

  def start_loop(self, timer, start_now, func, *args, **kwargs):
    """Continuously loop the passed function.

    Args:
      timer: How often to loop the call, in seconds.
      start_now: Boolean indicating whether the first iteration should happen
                 immediately or wait until after the first timer expires.
      func: The function to run.
      *args, **kwargs: Anything that needs to be passed to the function.
    """

    loop = task.LoopingCall(func, *args, **kwargs)
    deferred_task = loop.start(timer, now=start_now)
    deferred_task.addErrback(self.logger.error)

  def restart(self):
    """Setup an event to restart the agent after the reactor stops."""

    reactor.addSystemEventTrigger('after', 'shutdown',
                                  super(RealityAuditor, self).restart)
    reactor.callFromThread(reactor.stop)

  def auto_agent_update(self, update_path):
    """Checks for a new version of the running application from the remote server.
    If a new version is found, it will be downloaded and extracted, and the agent
    restarted. This only applies if the application is frozen.

    Args:
      update_path: The absolute URI of a listing of frozen versioned agent downloads.
    """

    updater = esky.Esky(sys.executable, update_path)
    self.logger.info('Checking for updates, currently running %s',
                     updater.active_version)

    new_version = updater.find_update()
    if new_version:
      self.logger.info('Version %s found', new_version)

      updater.auto_update(callback=self.logger.debug)
      self.logger.info('New version installed')

      self.restart()
    else:
      self.logger.info('No update found')
