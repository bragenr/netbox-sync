# -*- coding: utf-8 -*-
#  Copyright (c) 2020 - 2026 netbox-sync team. All rights reserved.
#
#  netbox-sync.py
#
#  This work is licensed under the terms of the MIT license.
#  For a copy, see file LICENSE.txt included in this
#  repository or visit <https://opensource.org/licenses/MIT>.

from module.common.support import normalize_mac_address
from module.netbox.inventory import NBIPAddress, NBVMInterface


def parse_interface_config(net_config=None):
    """
    Parse a Proxmox 'netX' or 'ipconfigX' value into a dict.

    Parameters
    ----------
    net_config: str
        value of the netX/ipconfigX option of a guest config

    Returns
    -------
    dict: parsed key/value pairs of the interface config
    """

    result = dict()

    if net_config is None:
        return result

    for part in str(net_config).split(","):

        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()
        else:
            result[part.strip()] = None

    return result


def get_interface_ips(interface_config=None, ipconfig=None):
    """
    Collect all static IP addresses (CIDR notation) of a guest interface.

    Parameters
    ----------
    interface_config: dict
        parsed 'netX' config of a guest
    ipconfig: str
        raw 'ipconfigX' value of a guest

    Returns
    -------
    list: list of IP addresses in CIDR notation
    """

    ip_addresses = list()

    ip_values = list()

    for key in ["ip", "ip6"]:
        if interface_config is not None and interface_config.get(key) is not None:
            ip_values.extend(str(interface_config.get(key)).split(" "))

    if ipconfig is not None:
        for key in ["ip", "ip6"]:
            value = parse_interface_config(ipconfig).get(key)
            if value is not None:
                ip_values.extend(str(value).split(" "))

    for value in ip_values:

        if "/" not in value:
            continue

        ip_addresses.append(value)

    return ip_addresses


def sync_vm_network(handler, vm, guest, vm_config):
    """
    Create interfaces + assign IPs for a Proxmox guest
    """

    inventory = handler.inventory

    for net_key in [key for key in vm_config.keys() if key.startswith("net") and key[3:].isdigit()]:

        interface_config = parse_interface_config(vm_config.get(net_key))

        interface_name = interface_config.get("name") or net_key.replace("net", "eth")

        interface = inventory.add_update_object(
            NBVMInterface,
            data={
                "name": interface_name[:64],
                "virtual_machine": vm,
                "enabled": True,
                "description": "bridge: %s" % interface_config.get("bridge") if interface_config.get("bridge") else None,
            },
            source=handler,
        )

        if interface_config.get("hwaddr") is not None:
            interface.update(
                data={"mac_address": normalize_mac_address(interface_config.get("hwaddr"))},
                source=handler)

        ipconfig_index = net_key.replace("net", "")
        assign_ips(
            inventory,
            handler,
            get_interface_ips(interface_config, vm_config.get(f"ipconfig{ipconfig_index}")),
            interface,
        )


def assign_ips(inventory, handler, ip_addresses, interface):
    """
    Assign IP addresses to a guest interface
    """

    for ip_addr in ip_addresses:

        ip_data = {
            "address": ip_addr,
            "assigned_object_type": "virtualization.vminterface",
            "assigned_object_id": interface,
        }

        existing_ip = next(
            (ip for ip in inventory.get_all_items(NBIPAddress)
             if ip.data.get("address") == ip_addr),
            None
        )

        if existing_ip is None:
            inventory.add_object(NBIPAddress, data=ip_data, source=handler)
        else:
            existing_ip.update(ip_data, source=handler)
