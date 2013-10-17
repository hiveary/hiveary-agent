#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved
"""

import copy
import datetime
import json
import kombu
import kombu.common
import logging
import oauth2
import os
import platform
import random
import socket
from ssl import CERT_REQUIRED, CERT_NONE
import subprocess
import sys
import time
import traceback

# Windows specific imports
if subprocess.mswindows:
  import pythoncom
  import wincom

# Local imports
from . import oauth_client
from . import paths
from . import sysinfo


class NetworkController(object):
  """Class used to handle network functions, such as the AMQP connection."""

  PING_TIMER = 120  # How often to ping the server, in seconds
  MAX_BACKOFF_MULTIPLE = 10

  def __init__(self, reactor=None, logger=None):
    """Initialze the controller.

    Args:
      reactor: A reference to the twisted reactor controlling the agent.
      logger: A logging object to use.
    """

    self.logger = logger or logging.getLogger('hiveary_agent.network')

    # Configuration values - most of these will be modified by the host's
    # configuration file
    self.running = True
    self.owner = ''
    self.hostname = ''
    self.access_token = 'hunter5'
    self.debug_mode = False
    self.disable_ssl_verification = False
    self.obj_id = None
    self.remote_host = ''
    self.amqp_server = ''
    self.ca_bundle = None
    self.current_system = platform.system()

    # AMQP connection values
    self.user_id = None
    self.amqp_password = None
    self.amqp = None

    # Thread and deferred management
    self.reactor = reactor

    self.expected_values = {}

  def initialize_amqp(self):
    """Method to establish an AMQP connection and consumers."""

    # Find out the credentials used for AMQP
    url = 'https://{host}/amqp/account?hostname={hostname}'.format(
        host=self.remote_host, hostname=self.hostname)
    resp, content = self.request_with_backoff(url, method='GET')

    if resp.status == 200:
      self.logger.info('Retrieved AMQP credentials')
      content_json = json.loads(content)
      self.amqp_password = content_json.get('amqp_password')
      self.user_id = content_json.get('user_id')
      self.obj_id = content_json.get('host_id')
    elif resp.status == 409:
      self.logger.error('Unable to connect this host to the server, '
                        'you\'ve already used all of your licenses. '
                        'Please vist https://%s/upgrade to upgrade your plan.',
                        self.remote_host)
      sys.exit(409)
    else:
      self.logger.error('Failed to retrieve AMQP credentials. Status: %s',
                   resp.status)
      sys.exit(resp.status)

    if self.obj_id is None or self.amqp_password is None or self.user_id is None:
      self.logger.error('Missing required parameters to establish an AMQP connection')
      sys.exit(1)

    # Create the connection
    ca_certs = os.path.join(paths.get_program_path(), 'ca-bundle.pem')
    self.logger.debug('Using SSL cert bundle at "%s"', ca_certs)

    ssl_options = {
        'ca_certs': ca_certs,
        'cert_reqs': CERT_REQUIRED,
      }
    # Disable certificate validation when debugging a non-frozen app or when
    # specifically told to as a startup arg
    if self.disable_ssl_verification:
      ssl_options['cert_reqs'] = CERT_NONE

    self.logger.debug('Connecting to %s as user %s', self.amqp_server, self.user_id)
    self.amqp = kombu.Connection(self.amqp_server, self.user_id, self.amqp_password,
                                 port=5671, ssl=ssl_options)
    self.logger.info('SSL-AMQP connection established')

    # Setup the consumers
    task_queue = kombu.Queue('agent.{user}.tasks.{host}'.format(
                             user=self.user_id, host=self.obj_id))
    task_consumer = self.amqp.Consumer(task_queue, auto_declare=False,
                                       callbacks=[self.task_callback])
    task_consumer.consume()
    self.reactor.callInThread(self.drain_events)

  def drain_events(self):
    """Attempts to receive a message from the AMQP server and times out after
    a short wait. Loops until the agent is marked as stopping. This allows us
    to gracefully close the connection when waiting for messages."""

    loop = kombu.common.eventloop(self.amqp, timeout=1, ignore_timeouts=True)
    while self.running:
      try:
        next(loop)
      except:
        # Errors generated while the agent is stopping can be ignored
        if self.running:
          raise

  def create_oauth_client(self):
    """Generates an OAuth client that handles the OAuth signature and header.

    Returns:
      The configured OAuth client, an instance of oauth2.Consumer.
    """

    consumer = oauth2.Consumer(key=self.owner, secret=self.access_token)
    try:
      client = oauth_client.OAuthClient(consumer, debug=self.debug_mode,
                                        disable_ssl_verification=self.disable_ssl_verification,
                                        ca_bundle=self.ca_bundle)
    except IOError:
      sys.exit(1)

    return client

  def request_with_backoff(self, url, attempt=0, **kwargs):
    """Makes an OAuth authenticated HTTPS request. If the request fails, it
    will be retried using an exponential backoff.

    Args:
      url: The absolute url of the server.
      attempt: The current attempt. Anything higher than 0 indicates that a
               previous attempt failed and the request is being retried. This
               is used as a multiple to determine how long to backoff.
      kwargs: Any extra arguments to pass to the client.
    Returns:
      A tuple of (response, content), the first being an instance of the
      'httplib2.Http.Response' class, the second being a string that
      contains the response entity body.
    """

    client = self.create_oauth_client()

    try:
      response = client.request(url, **kwargs)

      # Response is a 2-item tuple of headers, content
      self.logger.debug('Got back a response of %s', response[0].status)

      return response
    except socket.error:
      # Parse out extremely verbose/sensitive data
      logged_kwargs = kwargs.copy()
      if 'body' in logged_kwargs:
        del(logged_kwargs.body)

      self.logger.error('Socket error when attempting to send to %s with params %s:',
                        url, logged_kwargs, exc_info=traceback.format_exc())
      self.logger.debug('Verbose parameter information for errored request:\n%s',
                        kwargs)

      timer = (2 ** attempt) + (random.randint(0, 1000) / 1000.0)
      self.logger.error('Retrying in %.3f', timer)

      # Try again after the backoff and increment the attempts made
      time.sleep(timer)

      # Limit the upper end of the backoff timer
      if attempt < self.MAX_BACKOFF_MULTIPLE:
        attempt += 1

      return self.request_with_backoff(url, attempt, **kwargs)

  def publish_info_message(self, destination, message=''):
    """Method to publish an AMQP message.

    Args:
      destination: The AMQP routing key.
      message: The message to publish, as a string (usually a JSONified object).
    """

    self.logger.debug('Sending "%s" AMQP message', destination)

    exchange = kombu.Exchange('agent.{user}'.format(user=self.user_id))
    with self.amqp.Producer(exchange=exchange, routing_key=destination,
                            auto_declare=False) as producer:
      publish = self.amqp.ensure(producer, producer.publish, errback=self.amqp_errback,
                                 interval_start=5, interval_step=10, max_retries=5)
      publish(message, user_id=self.user_id, timestamp=datetime.datetime.utcnow())

  def amqp_errback(self, exc, interval):
    """Error callback fired when there is a problem with the connection or channel.

    Args:
      exc: The exception that occurred.
      interval: Amount of time before the message is attempted again.
    """

    self.logger.error("Couldn't publish message: %r. Retry in %ds", exc, interval)

  def ping_pong(self):
    """Function to alert the server that we're still alive and doing science."""

    # Send the ping
    data = {'host_id': self.obj_id}
    self.logger.debug('Sending ping to server with a body of: %s', data)
    self.publish_info_message('ping', json.dumps(data))

  def task_callback(self, body, message):
    """Callback for when a message is received from the tasks queue.

    Args:
      body: A string of the response sent back from the broker.
      message: The AMQP object containing metadata about the response.
    """

    self.logger.debug('Received the following task message: %s', body)

    try:
      data = json.loads(body)
    except ValueError:
      self.logger.error('Unable to process task:', exc_info=True)
    else:
      self.run_task(data)

    # Let the broker know that we're done processing this message
    message.ack()

  def run_task(self, client_task):
    """Run a task as commanded by the control server.

    Args:
      client_task: A dictionary of the task to attempt.
    """

    # Start creating the response to send back to the server
    data = {'id': client_task.get('id')}
    task_name = client_task['command']['name']
    routing_key = 'task_complete'

    if task_name == 'refresh':
      # Re-poll available system data
      item = client_task['command'].get('item', 'all')
      self.logger.debug('Retrieving %s information', item)
      info_method = getattr(sysinfo, 'pull_{item}'.format(item=item))

      routing_key = '{user}.{host}.{item}'.format(user=self.user_id,
                                                  host=self.obj_id, item=item)

      data['info'] = info_method()
      data['status'] = 'SUCCESS'
    elif task_name == 'com':
      # Run a command using the Windows COM interface
      if self.current_system == 'Windows':
        interface = client_task['command']['interface']
        item = client_task['command']['item']

        try:
          com_client = wincom.WindowsCOMClient(interface)

          # Check if are retrieving or setting information
          if client_task['command']['action'] == 'set':
            value = client_task['command']['value']
            com_client.set_item(value, item)
          elif client_task['command']['action'] == 'get':
            value = com_client.get_item(item)
            data['info'] = {'item': item, 'value': value}
          else:
            self.logger.error('Unable to perform requested COM action')
            data['status'] = 'NOT_IMPLEMENTED'
        except pythoncom.com_error, error:
          # A com_error likely indicates a bad interface name or item name, so we
          # should mark the task as incompleteable
          data['status'] = 'FAILURE'
          data['info'] = error.strerror
      else:
        self.logger.error('COM interface is only accessible on Windows systems')
        data['status'] = 'FAILURE'
    elif task_name == 'expected_update':
      expected_values = client_task['command']['expected']
      monitor_name = client_task['command']['monitor']
      self.logger.info('Received new %s expected values: %s',
                       monitor_name, expected_values)

      self.expected_values[monitor_name] = copy.copy(expected_values)
    else:
      self.logger.error('Unable to perform requested task')
      data['status'] = 'NOT_IMPLEMENTED'

    if data['id'] is not None or routing_key != 'task_complete':
      self.publish_info_message(routing_key, json.dumps(data))
      self.logger.info('Sent task completion to server')
