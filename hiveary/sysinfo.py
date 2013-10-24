#!/usr/bin/env python
"""
Hiveary
https://hiveary.com

Licensed under Simplified BSD License (see LICENSE)
(C) Hiveary, LLC 2013 all rights reserved

Functions for collecting local system information.
"""

import logging
import netifaces
import os
import platform
import psutil
import simplejson
import socket
import subprocess

if subprocess.mswindows:
  import win32net
  import win32service

  import wincom
else:
  import grp
  import pwd


logger = logging.getLogger('hiveary_agent.sysinfo')
current_system = platform.system()


def find_valid_disks():
  """Iterate through and find all valid disk partitions. Some devices will not
  be accessible since they have non-disk filesystems, such as a CD-ROM drive.

  Returns:
    A list of all valid disks.
  """

  disks = []
  for disk in psutil.disk_partitions():
    try:
      psutil.disk_usage(disk.device)
    except OSError:
      continue
    else:
      disks.append(disk.device)

  return disks


def pull_all():
  """Finds all available static information about the host.

  Returns:
    A dictionary containing all discovered information.
  """

  logger.info('Pulling all local info')
  info = {}

  info['os'], info['processor'] = pull_os()
  info['disks'] = pull_disks()
  info['fqdn'], info['interfaces'] = pull_net()
  info['users'] = pull_users()
  info['groups'] = pull_groups()
  info['services'] = pull_services()
  info['automatic_update_settings'] = pull_update_settings()

  return info


def pull_os():
  """Find information about the host's operating system.

  Returns:
    A tuple of a dictionary of the OS information, and the system's processor.

    Example:
    (
     {
       'architecture': 'nt',
        'platform': 'Windows',
        'release': {
          'product_name': 'Windows 8',
          'service_pack': 0,
          'version_number': '6.2'
      },
     'Intel64 Family 6 Model 58 Stepping 9, GenuineIntel'
    )
  """

  os_info = {}
  os_info['architecture'] = os.name
  os_info['platform'] = current_system
  if current_system == 'Windows':
    os_info['release'] = wincom.get_version_info()
  else:
    os_info['release'] = platform.release()

  processor = platform.processor()

  return (os_info, processor)


def pull_disks():
  """Finds full disk information from the host.

  Returns:
    A dictionary of all disk-like devices mapped to their data. Example:

    {
      'C:\\': {'filesystem': 'NTFS', 'mountpoint': 'C:\\', 'options': 'rw,fixed'},
      'D:\\': {'filesystem': 'NTFS', 'mountpoint': 'D:\\', 'options': 'rw,fixed'},
      'E:\\': {'filesystem': 'NTFS', 'mountpoint': 'E:\\', 'options': 'rw,fixed'},
      'H:\\': {'filesystem': '', 'mountpoint': 'H:\\', 'options': 'cdrom'}
    }
  """

  disks = {}
  for disk in psutil.disk_partitions():
    disks[disk.device] = {
        'mountpoint': disk.mountpoint,
        'filesystem': disk.fstype,
        'options': disk.opts,
        }
  return disks


def pull_net():
  """Finds network related information.

  Returns:
    A tuple of the host's FQDN and a list of network interfaces. Each network
    interface in the list is a dictionary of the interface properties. Example:

    (
      'prism7.utah.nsa.gov',
      [
        {
        'af_inet': {
          'addr': '127.0.0.1',
          'netmask': '255.0.0.0',
          'peer': '127.0.0.1'
        },
        'af_inet6': {
          'addr': '::1',
          'netmask': 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff'},
          'af_packet': {
            'addr': '00:00:00:00:00:00',
            'peer': '00:00:00:00:00:00'
          },
        'name': 'lo'
        },
        ...
      ]
    )
  """

  fqdn = socket.getfqdn()
  interfaces = []
  for iface in netifaces.interfaces():
    ifaddrs = netifaces.ifaddresses(iface)
    interface = {'name': iface}

    # Translate the address family identifier to a name
    for num, addrs in ifaddrs.iteritems():
      family = netifaces.address_families[num]

      # Parse out the netmask for IPv6
      if family == 'AF_INET6':
        addresses = []
        for address in addrs:
          addr = address.pop('addr')
          split_addr = addr.split('%')
          address['addr'] = split_addr[0]

          if len(split_addr) == 2:
            address['scope_id'] = split_addr[1]

          addresses.append(address)
      else:
        addresses = addrs

      if len(addresses) == 1:
        addresses = addresses[0]
      interface[family.lower()] = addresses

    interfaces.append(interface)

  logger.debug('Retrieved info on %s interfaces', len(interfaces))
  return (fqdn, interfaces)


def pull_users():
  """Finds local user information.

  Returns:
    A list of users. Each user is a dictionary of user data. Example:

    [
      {
        'gecos': 'root',
        'gid': 0,
        'homedir': '/root',
        'name': 'root',
        'shell': '/bin/bash',
        'uid': 0
      },
      ...
    ]
  """

  if current_system == 'Windows':
    net_users = win32net.NetUserEnum(None, 3)
    logger.debug('Found %s users', len(net_users[0]))
    resume = net_users[2]

    for user in net_users[0]:
      del(user['logon_hours'])  # Hex isn't JSONable
    users = net_users[0]

    while resume != 0:
      net_users = win32net.NetUserEnum(None, 3, resumeHandle=resume)
      logger.debug('Found %s users', len(net_users[0]))
      resume = net_users[2]

      for user in net_users[0]:
        del(user['logon_hours'])  # Hex isn't JSONable
      users.append(net_users[0])
  elif current_system == 'Linux' or current_system == 'Darwin':
    # pwd/grp work on linux and osx
    users = []
    users_pwd = pwd.getpwall()
    for user_pwd in users_pwd:
      user = {
          'name': user_pwd.pw_name,
          'uid': user_pwd.pw_uid,
          'gid': user_pwd.pw_gid,
          'gecos': user_pwd.pw_gecos,
          'homedir': user_pwd.pw_dir,
          'shell': user_pwd.pw_shell
        }
      users.append(user)
  else:
    logger.error('Unkown platform "%s", cannot pull users', current_system)
    return []

  return users


def pull_groups():
  """Finds local group information.

  Returns:
    A list of groups. Each group is a dictionary of information about the group.

    Example:
    [
      {
        'gid': 0,
        'members': ['root'],
        'name': 'root'
      },
      ...
    ]
  """

  if current_system == 'Windows':
    net_local_groups = win32net.NetLocalGroupEnum(None, 1)
    logger.debug('Found %s groups', len(net_local_groups[0]))
    resume = net_local_groups[2]
    groups = net_local_groups[0]

    while resume != 0:
      net_local_groups = win32net.NetLocalGroupEnum(None, 1, resumeHandle=resume)
      logger.debug('Found %s groups', len(net_local_groups[0]))
      resume = net_local_groups[2]
      groups.extend(net_local_groups[0])

    # Enumerate group members
    for group in groups:
      net_members = win32net.NetLocalGroupGetMembers(None, group['name'], 1)
      resume = net_members[2]
      group['members'] = [x['name'] for x in net_members[0]]

      while resume != 0:
        net_members = win32net.NetLocalGroupGetMembers(None, group['name'], 1, resumeHandle=resume)
        resume = net_members[2]
        group['members'].extend([x['name'] for x in net_members[0]])
  elif current_system == 'Linux' or current_system == 'Darwin':
    groups = []
    groups_grp = grp.getgrall()
    for group_grp in groups_grp:
      group = {
          'name': group_grp.gr_name,
          'gid': group_grp.gr_gid,
          'members': group_grp.gr_mem
        }
      groups.append(group)
  else:
    logger.error('Unkown platform "%s", cannot pull groups', current_system)
    return []

  return groups


def pull_services():
  """Finds information about installed services, currently only applicable to
  Windows.

  Returns:
    A dictionary of service name mapped to service information. All strings will
    be in unicode. The service information primarily includes the user-displayed
    service name and a dictionary of status information. Example:

    {
      u'wuauserv': {
        'display_name': u'Windows Update',
        'status': {
          'checkpoint': 0,
          'controls_accepted': 0,
          'service_exit_code': 0,
          'state': 1,
          'type': 32,
          'wait_hint': 0,
          'win32_exit_code': 0
        }
      },
      ...
    }
  """

  if current_system == 'Windows':
    services = {}
    scm = win32service.OpenSCManager(
        None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)

    raw_services = win32service.EnumServicesStatus(
        scm, win32service.SERVICE_WIN32)
    scm.Close()

    # Parse the services into something useful
    for raw_service in raw_services:
      service = {}
      service['display_name'] = raw_service[1]

      # Parse the status flags into meaningful names
      raw_status = raw_service[2]
      status = {
          'type': raw_status[0],
          'state': raw_status[1],
          'controls_accepted': raw_status[2],
          'win32_exit_code': raw_status[3],
          'service_exit_code': raw_status[4],
          'checkpoint': raw_status[5],
          'wait_hint': raw_status[6]
        }

      service['status'] = status

      # Key the service by ServiceName
      services[raw_service[0]] = service
  else:
    # TODO: nix services and osx services
    logger.warn('Service enumeration not implemented for %s', current_system)
    return {}

  logger.debug('Retrieved the services info')
  return services


def pull_processes(top=None, top_number=5):
  """Retrieves information about active processes.

  Args:
    top: If provided, the `top_number` of processes for the matching
        resource will be returned. Valid options are memory_percent or
        cpu_percent
    top_number: Number of top processes to return for the given resource. Only
        valid when top is not None.
  Returns:
    Returns a tuple of (all processes, top processes).
    Each process in the list is a dictionary with nicode keys containing
    a large amount of detailed information for the process. Example:

    [
      {
        u'cmdline': [],
        u'connections': [
          {
            u'family': 23,
            u'fd': -1,
            u'laddr': [u'::1', 8888],
            u'raddr': [u'::1', 52912],
            u'status': u'TIME_WAIT',
            u'type': 1
          },
          ...
        ],
        u'cpu_affinity': None,
        u'cpu_percent': 0.0,
        u'cpu_times': {u'system': 526099.53125, u'user': 0.0},
        u'create_time': 1381682351.719,
        u'cwd': None,
        u'exe': None,
        u'ext_memory_info': {
          u'nonpaged_pool': 0,
          u'num_page_faults': 0,
          u'paged_pool': 0,
          u'pagefile': 0,
          u'peak_nonpaged_pool': 0,
          u'peak_paged_pool': 0,
          u'peak_pagefile': 0,
          u'peak_wset': 0,
          u'private': 0,
          u'wset': 20480
        },
        u'io_counters': {
          u'read_bytes': 0,
          u'read_count': 0,
          u'write_bytes': 0,
          u'write_count': 0
        },
        u'ionice': None,
        u'memory_info': {u'rss': 20480, u'vms': 0},
        u'memory_maps': None,
        u'memory_percent': 0.00023943963463427274,
        u'name': u'System Idle Process',
        u'nice': None,
        u'num_ctx_switches': {u'involuntary': 0, u'voluntary': 703011786},
        u'num_handles': 0,
        u'num_threads': 4,
        u'open_files': [],
        u'pid': 0,
        u'ppid': 0,
        u'status': u'running',
        u'threads': None,
        u'username': u'NT AUTHORITY\\SYSTEM'
      },
      ...
    ]
  """

  # Create a JSONable version of the process list
  processes = []
  for p in psutil.process_iter():
    try:
      processes.append(simplejson.loads(simplejson.dumps(p.as_dict())))
    except psutil.NoSuchProcess:
      # Likely poor timing for a terminating process, not worth logging
      continue
    except OSError:
      if p.name == 'System':
        # System cannot be converted to a dict, just ignore it
        continue
      else:
        raise

  # Find the top processes
  top_procs = []
  if top:
    full_top_procs = sorted(processes, key=lambda p: p[top], reverse=True)
    top_procs = []

    for i in xrange(0, top_number):
      try:
        proc = full_top_procs[i]
      except IndexError:
        break

      # Pull out just a subset of information
      proc_subset = {
          'name': proc['name'],
          'pid': proc['pid'],
          top: proc[top],
      }
      top_procs.append(proc_subset)

    logger.debug('Top processes for %s: %s', top, top_procs)

  logger.debug('Retrieved the running processes')
  return processes, top_procs


def pull_update_settings():
  """Retrieves information about the system's auto update settings, currently
  only applicable to Windows.

  Retruns:
    A dictionary of the update settings. Example:

    {
      'service_enabled': True,
      'notification_level': 'Scheduled Installation',
      'installation_schedule': {'day': 'Every Day', 'time': '03:00'}
    }
  """

  logger.debug('Retrieving system update settings.')

  if current_system == 'Windows':
    automatic_update_settings = wincom.get_update_settings()
    logger.debug('Retrieved the following update settings: %s',
                 automatic_update_settings)
  else:
    automatic_update_settings = {}

  return automatic_update_settings
