#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved
"""

import glob
import impala
import importlib
import inspect
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
from . import __version__
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
  MONITORS_DIR = '/usr/lib/hiveary/'  # Default location to find monitor modules

  def __init__(self, parsed_args, stored_config, logger=None):
    """Initialization when the agent is started.

    Args:
      parsed_args: A dictionary version of the parsed command line arguments.
      stored_config: A dictionary of any values from the config file.
      logger: Optional, the logger that this class should log to.
    """

    self.logger = logger or logging.getLogger('hiveary_agent.controller')

    # Check that the directory for the pid file exists, and if not then use
    # the same directory as the config file
    pid_file = stored_config.get('pid_file', self.PID_FILE)
    if not os.path.isdir(os.path.dirname(pid_file)):
      directory = os.path.dirname(stored_config['filename'])
      filename = os.path.basename(pid_file)
      pid_file = os.path.join(directory, filename)

    # Check if the monitors directory exists, otherwise, place it under the
    # location of the config file
    self.monitors_dir = stored_config.get('monitors_dir') or self.MONITORS_DIR
    if not os.path.isdir(self.monitors_dir):
      directory = os.path.dirname(stored_config['filename'])
      self.monitors_dir = os.path.join(directory, 'monitors')
      if not os.path.isdir(self.monitors_dir):
        os.makedirs(self.monitors_dir)

    self.monitors = []

    # Get and possibly save optional configuration parameters. If the defaults
    # are used, they won't be saved.
    self.extra_options = {}
    for option in ('monitor_backoff', 'pid_file', 'ca_bundle', 'monitors_dir'):
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

    self.network_controller.ensure_internet_connection()

    if hasattr(sys, 'frozen'):
      # Setup the auto-updater
      update_path = 'https://{host}/versions'.format(host=self.network_controller.remote_host)
      self.app = esky.Esky(sys.executable, update_path)
      reactor.callLater(0, self.start_loop, self.UPDATE_TIMER,
                        self.auto_agent_update)

    # Load all monitors
    self.load_monitors()

    # Connect to the server
    self.network_controller.initialize_amqp()

    # Start all of our monitors
    for monitor in self.monitors:
      self.start_monitor(monitor)

    # Send the first data dump
    data = sysinfo.pull_all()
    data['version'] = __version__
    data['host_id'] = self.network_controller.obj_id
    data['monitors'] = []
    for monitor in self.monitors:
      monitor_data = {
          'name': monitor.NAME,
          'sources': monitor.SOURCES,
          'id': monitor.UID,
          'type': monitor.TYPE,
      }
      data['monitors'].append(monitor_data)
    reactor.callLater(self.INITIAL_DELAY,
                      self.network_controller.publish_info_message,
                      'startup',
                      json.dumps(data))

    # Send a ping to the server to act as a keep-alive.
    reactor.callLater(self.INITIAL_DELAY, self.start_loop,
                      self.network_controller.PING_TIMER,
                      self.network_controller.ping_pong)

    reactor.run()

  def load_monitors(self):
    """Loads all monitors from the config file. If it cannot find a configured module,
    it will attempt to download one.
    """

    # Check that we have monitors enabled in the config, and know where to find them
    if self.monitors_dir:
      # Add the monitors dir to path so we can import monitors
      self.logger.info('Loading monitors from %s', self.monitors_dir)
      sys.path.insert(0, self.monitors_dir)

      # When frozen, the monitors included with the current version also
      # need to be loaded
      if hasattr(sys, 'frozen'):
        frozen_monitors_dir = os.path.join(os.path.dirname(sys.executable),
                                           'monitors')
        sys.path.insert(0, frozen_monitors_dir)
        self.logger.debug('Also loading frozen monitors from: %s',
                          frozen_monitors_dir)

      # Find all of the monitor modules.
      monitor_map = {}
      for filename in glob.glob('%s/*.py' % self.monitors_dir):
        monitor = os.path.basename(filename).split('.')[0]
        monitor_map['hiveary.monitors.%s' % monitor] = filename

      # Import all of the monitors and add the instances to our monitor list.
      impala.register(monitor_map)
      object_filter = lambda obj: inspect.isclass(obj) and monitors.BaseMonitor in inspect.getmro(obj)
      for module_name in monitor_map.keys():
        try:
          module = importlib.import_module(module_name)
        except ImportError:
          self.logger.error('Failed to import module %s', module_name)
          continue

        # Filter down to all classes that inherit the monitors.BaseMonitor class.
        for class_name, monitor_class in inspect.getmembers(module, object_filter):
          self.logger.info('Loading %s from %s', class_name, module_name)
          try:
            monitor = monitor_class()
          except Exception:
            self.logger.error('Failed to load class %s from module %s',
                              class_name, module_name)
            self.logger.debug('Full loading error:', exc_info=True)
          else:
            self.monitors.append(monitor)

  def start_monitor(self, monitor):
    """Starts a given monitor.

    Args:
      monitor: Instance of a monitor class
    """

    self.logger.debug('Starting %s (%s) monitor data checks', monitor.NAME,
                      monitor.UID)
    self.network_controller.monitors[monitor.UID] = monitor
    monitor.send_alert = self.network_controller.publish_alert_message

    # Check if the monitor should run in a loop
    if monitor.MONITOR_TIMER is not None:
      self.start_loop(monitor.MONITOR_TIMER, monitor.run)
    else:
      reactor.callInThread(monitor.run)

    self.start_aggregation_loop(monitor)

  def signal_handler(self, signum, stackframe):
    """Handles a SIGTERM or SIGINT sent to the process.

    Args:
      signum: The number of the signal. SIGINT is 2, SIGTERM is 15.
      stackframe: The interrupted stack frame.
    """

    self.logger.info("Received signal: %s", signum)
    self.shutdown()

  def shutdown(self):
    """Stops the agent and any active network connections."""

    # Clean up the daemon after the reactor is done
    reactor.addSystemEventTrigger('after', 'shutdown', self.delpid)

    self.network_controller.stop_amqp()
    reactor.stop()

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
    if args.get('update'):
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
        'monitors': self.monitor_config,
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
    else:
      delta = monitor.AGGREGATION_TIMER

    reactor.callLater(int(delta), self.start_loop,
                      monitor.AGGREGATION_TIMER,
                      monitor.send_data, self.network_controller)

  def start_loop(self, timer, func, *args, **kwargs):
    """Continuously loop the passed function.

    Args:
      timer: How often to loop the call, in seconds.
      func: The function to run.
      *args, **kwargs: Anything that needs to be passed to the function.
    """

    loop = task.LoopingCall(func, *args, **kwargs)
    deferred_task = loop.start(timer, now=True)
    deferred_task.addErrback(self.logger.error)

  def restart(self):
    """Setup an event to restart the agent after the reactor stops."""

    self.logger.warn('The agent is restarting...')

    reactor.addSystemEventTrigger('after', 'shutdown', self.fork,
                                  detached=False, exit=False)
    self.shutdown()

  def auto_agent_update(self):
    """Checks for a new version of the running application from the remote server.
    If a new version is found, it will be downloaded and extracted, and the agent
    restarted. This only applies if the application is frozen."""

    self.logger.info('Checking for updates, currently running %s',
                     self.app.active_version)

    new_version = self.app.find_update()
    if new_version:
      self.logger.info('Version %s found', new_version)

      self.app.auto_update(callback=self.logger.debug)
      self.logger.info('New version installed')

      self.restart()
    else:
      self.logger.info('No update found')
