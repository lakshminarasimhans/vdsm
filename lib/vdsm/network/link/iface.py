# Copyright 2016-2017 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#
from __future__ import absolute_import

import abc
import os
import random
import string

import six

from vdsm.network import ipwrapper
from vdsm.network.link import dpdk
from vdsm.network.netlink import libnl
from vdsm.network.netlink import link
from vdsm.network.netlink.waitfor import waitfor_linkup


STATE_UP = 'up'
STATE_DOWN = 'down'

NET_PATH = '/sys/class/net'

DEFAULT_MTU = 1500


@six.add_metaclass(abc.ABCMeta)
class IfaceAPI(object):
    """
    Link iface driver interface.
    """
    @abc.abstractmethod
    def up(self, admin_blocking=True, oper_blocking=False):
        """
        Set link state to UP, optionally blocking on the action.
        :param dev: iface name.
        :param admin_blocking: Block until the administrative state is UP.
        :param oper_blocking: Block until the link is operational.
        admin state is at kernel level, while link state is at driver level.
        """

    @abc.abstractmethod
    def down(self):
        pass

    @abc.abstractmethod
    def properties(self):
        pass

    @abc.abstractmethod
    def is_up(self):
        pass

    @abc.abstractmethod
    def is_admin_up(self):
        pass

    @abc.abstractmethod
    def is_oper_up(self):
        pass

    @abc.abstractmethod
    def is_promisc(self):
        pass

    @abc.abstractmethod
    def exists(self):
        pass

    @abc.abstractmethod
    def address(self):
        pass

    @abc.abstractmethod
    def set_address(self, address):
        pass

    @abc.abstractmethod
    def mtu(self, properties=None):
        pass


class IfaceHybrid(IfaceAPI):
    """
    Link iface driver implemented by a mix of iproute2, netlink and sysfs.
    """
    def __init__(self):
        self._dev = None
        self._vfid = None
        self._is_dpdk_type = None

    @property
    def device(self):
        return self._dev

    @device.setter
    def device(self, dev):
        if self._dev:
            raise AttributeError('Constant attribute, unable to modify')
        self._dev = dev

    @property
    def vfid(self):
        return self._vfid

    @vfid.setter
    def vfid(self, vf):
        if self._vfid:
            raise AttributeError('Constant attribute, unable to modify')
        self._vfid = vf

    def properties(self):
        if self._is_dpdk_type:
            info = dpdk.link_info(self._dev)
        else:
            info = link.get_link(self._dev)
        return info

    def up(self, admin_blocking=True, oper_blocking=False):
        if self._is_dpdk_type:
            dpdk.up(self._dev)
            return
        if admin_blocking:
            self._up_blocking(oper_blocking)
        else:
            ipwrapper.linkSet(self._dev, [STATE_UP])

    def down(self):
        if self._is_dpdk_type:
            dpdk.down(self._dev)
            return
        ipwrapper.linkSet(self._dev, [STATE_DOWN])

    def is_up(self):
        return self.is_admin_up()

    def is_admin_up(self):
        properties = self.properties()
        return link.is_link_up(properties['flags'], check_oper_status=False)

    def is_oper_up(self):
        if self._is_dpdk_type:
            return dpdk.is_oper_up(self._dev)
        properties = self.properties()
        return link.is_link_up(properties['flags'], check_oper_status=True)

    def is_promisc(self):
        properties = self.properties()
        return bool(properties['flags'] & libnl.IfaceStatus.IFF_PROMISC)

    def exists(self):
        if dpdk.is_dpdk(self._dev):
            return self._dev in dpdk.get_dpdk_devices()
        return os.path.exists(os.path.join(NET_PATH, self._dev))

    def address(self):
        return self.properties()['address']

    def set_address(self, address):
        if self._vfid is None:
            link_set_args = ['address', address]
        else:
            link_set_args = ['vf', str(self._vfid), 'mac', address]
        ipwrapper.linkSet(self._dev, link_set_args)

    def mtu(self):
        return self.properties()['mtu']

    def _up_blocking(self, link_blocking):
        with waitfor_linkup(self._dev, link_blocking):
            ipwrapper.linkSet(self._dev, [STATE_UP])


def iface(device, vfid=None):
    """ Iface factory """
    interface = IfaceHybrid()
    interface.device = device
    interface._is_dpdk_type = dpdk.is_dpdk(device)
    interface.vfid = vfid
    return interface


def up(dev, admin_blocking=True, oper_blocking=False):
    """
    Set link state to UP, optionally blocking on the action.
    :param dev: iface name.
    :param admin_blocking: Block until the administrative state changes to UP.
    :param oper_blocking: Block until the link is operational.
    admin state is at kernel level, while link state is at driver level.
    """
    iface(dev).up(admin_blocking, oper_blocking)


def down(dev):
    iface(dev).down()


def is_up(dev):
    return iface(dev).is_up()


def is_admin_up(dev):
    return iface(dev).is_admin_up()


def is_oper_up(dev):
    return iface(dev).is_oper_up()


def is_promisc(dev):
    return iface(dev).is_promisc()


def exists(dev):
    return iface(dev).exists()


def set_mac_address(dev, mac_address, vf_num=None):
    iface(dev, vf_num).set_address(mac_address)


def mac_address(dev):
    return iface(dev).address()


def get_mtu(dev):
    return iface(dev).mtu()


def random_iface_name(prefix='', max_length=15, digit_only=False):
    """
    Create a network device name with the supplied prefix and a pseudo-random
    suffix, e.g. dummy_ilXaYiSn7. The name is bound to IFNAMSIZ of 16-1 chars.
    """
    suffix_len = max_length - len(prefix)
    suffix_chars = string.digits
    if not digit_only:
        suffix_chars += string.ascii_letters
    suffix = ''.join(random.choice(suffix_chars)
                     for _ in range(suffix_len))
    return prefix + suffix
