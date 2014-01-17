#!/usr/bin/env python

"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, Inc. 2013-2014 all rights reserved
"""

import platform
import sys

from hiveary import __version__ as version


current_platform = platform.system()

FROZEN_NAME = 'hiveary-agent'
AUTHOR = "Hiveary"
AUTHOR_EMAIL = "info@hiveary.com"
DESCRIPTION = "Hiveary Monitoring Agent"
LICENSE = "Simplified BSD"
URL = "http://hiveary.com"


# OS-specific setup
if 'bdist_esky' in sys.argv and current_platform == 'Windows':
  # Use esky/cxfreeze to build the agent and py2exe to build the service
  from esky.bdist_esky import Executable
  from glob import glob
  import os
  import py2exe  # noqa
  import setuptools
  import shutil

  modules = [
      'kombu.transport.pyamqp',
      'kombu.transport.base',
      'kombu.transport.amqplib',
  ]

  sys.path.append('C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\redist\\x86\\Microsoft.VC90.CRT')

  # Add in Visual Studio C++ compiler library
  data_files = [
      ('Microsoft.VC90.CRT', glob(r'C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\redist\x86\Microsoft.VC90.CRT\*.*')),
      r'hiveary\ca-bundle.pem',
      ('monitors', glob(r'monitors\*.py'))
  ]

  script = Executable('hiveary-agent', gui_only=False)

  options = {
      'bdist_esky': {
          'freezer_module': 'cxfreeze',
          'includes': modules,
      }
  }

  # Build the agent
  setuptools.setup(name=FROZEN_NAME,
                   version=version,
                   scripts=[script],
                   options=options,
                   data_files=data_files,
                   )

  sys.argv.remove('bdist_esky')
  sys.argv.append('py2exe')

  # used for the versioninfo resource
  class Target(object):
    def __init__(self, **kw):
      self.__dict__.update(kw)
      self.version = version
      self.company_name = 'Hiveary'
      self.name = "HivearyService"

  script = Target(
      description='Hiveary Agent Service Launcher',
      modules=["HivearyService"],
      cmdline_style='pywin32')

  data_files = []

  # Build the service
  setuptools.setup(name='HivearyService',
                   version=version,
                   options={'py2exe': {}},
                   service=[script]
                   )

  # python27.dll will be available at the root once the esky zip is extracted,
  # so we can remove it now
  os.remove(r'dist\python27.dll')
  shutil.rmtree('build')

else:
  try:
    from setuptools import setup, find_packages
  except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup, find_packages

  # Include all files from the package.
  install_requires = [
      'amqplib>=1.0.2',
      'kombu>=3.0.8',
      'netifaces>=0.7',
      'oauth2>=1.5.211',
      'psutil>=1.1.0',
      'simplejson>=3.0.5',
      'Twisted>=13.2.0',
      'impala>=0.1.1',
  ]

  data_files = [
      ('/etc/hiveary', ['hiveary.conf.example', 'README.md']),
      ('/etc/hiveary/init', ['initd/hiveary-agent']),
      ('/etc/hiveary/systemd', ['arch/hiveary-agent.service']),
      ('/usr/lib/hiveary', ['monitors/resources.py']),
  ]

  setup(name=FROZEN_NAME,
        version=version,
        author=AUTHOR,
        author_email=AUTHOR_EMAIL,
        description=DESCRIPTION,
        license=LICENSE,
        url=URL,
        include_package_data=True,
        data_files=data_files,
        install_requires=install_requires,
        packages=find_packages(),
        scripts=['hiveary-agent']
        )
