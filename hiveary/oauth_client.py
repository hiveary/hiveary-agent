#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved
"""

import httplib2
import logging
from oauth2 import Consumer, Client, Request, Token, SignatureMethod_HMAC_SHA1
import os
import urllib
from urlparse import parse_qs

# Local imports
from . import paths


class OAuthClient(Client):
  """Subclass of the oauth Client that allows the use of header auth."""

  def __init__(self, consumer, token=None, cache=None, timeout=None,
               proxy_info=None, debug=False, disable_ssl_verification=False,
               ca_bundle=None, logger=None):
    """Initialize the client.

    Args:
      consumer: An instance of oauth2.Consumer, used for 2-legged OAuth requests
      token: An instance of oauth2.Token, used for 2-legged OAuth requests
      cache: If 'cache' is a string then it is used as a directory name for
             a disk cache. Otherwise it must be an object that supports the
             same interface as httplib2.FileCache.
      timeout: Timeout in seconds. If None is passed for timeout
               then Python's default timeout for sockets will be used. See
               for example the docs of socket.setdefaulttimeout():
               http://docs.python.org/library/socket.html#socket.setdefaulttimeout
      proxy_info: May be:
                  - a callable that takes the http scheme ('http' or 'https') and
                    returns a httplib2.ProxyInfo instance per request.
                    By default, uses proxy_nfo_from_environment.
                  - a httplib2.ProxyInfo instance (static proxy config).
                  - None (proxy disabled).
      debug: Boolean indicating whether the agent is running in debug mode.
      disable_ssl_verification: Boolean indicating whether the server's SSL
                                certificate should be verified.
      ca_bundle: The full path to the CA bundle used for SSL verification.
      logger: An existing logging object to use.
    Raises:
      IOError: The CA bundle was not found on the system, and SSL verification
               is enabled.
    """

    self.logger = logger or logging.getLogger('hiveary_agent.oauth')

    if consumer is not None and not isinstance(consumer, Consumer):
        raise ValueError("Invalid consumer.")

    if token is not None and not isinstance(token, Token):
        raise ValueError("Invalid token.")

    self.consumer = consumer
    self.token = token
    self.method = SignatureMethod_HMAC_SHA1()

    if ca_bundle is None or not os.path.isfile(ca_bundle):
      ca_bundle = os.path.join(paths.get_program_path(), 'ca-bundle.pem')

    self.logger.debug('Using %s as the CA bundle', ca_bundle)

    if disable_ssl_verification:
      self.logger.warn('SSL validation is disabled')
    elif not os.path.isfile(ca_bundle):
      self.logger.error('CA bundle %s does not exist!', ca_bundle)
      raise IOError('File does not exist')

    httplib2.Http.__init__(self, cache=cache, timeout=timeout,
                           proxy_info=proxy_info, ca_certs=ca_bundle,
                           disable_ssl_certificate_validation=disable_ssl_verification)

  def request(self, uri, method="GET", body='', headers=None,
              redirections=httplib2.DEFAULT_MAX_REDIRECTS, connection_type=None):
    """Creates and sends a two-legged OAuth 1.0a authenticated request.

    Args:
      uri: The absolute uri of the server.
      method: The HTTP method to use.
      body: Any body that should go with the request, as a string.
      headers: A dictionary of any extra heders to include.
      redirection: Passed directly to httplib2
      connection_type: Passed directly to httplib2
    Returns:
      A tuple of (response, content), the first being an instance of the
      'httplib2.Http.Response' class, the second being a string that
      contains the response entity body.
    """

    DEFAULT_POST_CONTENT_TYPE = 'application/x-www-form-urlencoded'

    # Body must be a string for the OAuth signature
    if body is None:
      body = ''

    if not isinstance(headers, dict):
      headers = {}

    if method == "POST":
      headers['Content-Type'] = headers.get('Content-Type',
                                            DEFAULT_POST_CONTENT_TYPE)

    is_form_encoded = headers.get('Content-Type') == 'application/x-www-form-urlencoded'

    if is_form_encoded and body:
      parameters = parse_qs(body)
    else:
      parameters = None

    req = Request.from_consumer_and_token(
        self.consumer, token=self.token, http_method=method, http_url=uri,
        parameters=parameters, body=body, is_form_encoded=is_form_encoded)

    req.sign_request(self.method, self.consumer, self.token)

    schema, rest = urllib.splittype(uri)
    if rest.startswith('//'):
      hierpart = '//'
    else:
      hierpart = ''
    host, rest = urllib.splithost(rest)

    realm = schema + ':' + hierpart + host

    if is_form_encoded:
      body = req.to_postdata()

    headers.update(req.to_header(realm=realm))

    self.logger.info('Sending %s %s', method, uri)

    return httplib2.Http.request(
        self, uri, method=method, body=body,
        headers=headers, redirections=redirections,
        connection_type=connection_type)
