# -*- coding: utf-8 -*-
#  Copyright (c) 2020 - 2026 netbox-sync team. All rights reserved.
#
#  netbox-sync.py
#
#  This work is licensed under the terms of the MIT license.
#  For a copy, see file LICENSE.txt included in this
#  repository or visit <https://opensource.org/licenses/MIT>.

from module.common.logging import get_logger

log = get_logger()


class ProxmoxClient:
    """
    Thin wrapper around proxmoxer to interact with a Proxmox VE API endpoint.
    Only plain dicts and lists are returned, so the rest of the source and the
    tests do not need to know about the proxmoxer API objects.
    """

    def __init__(self, host=None, user=None, port=8006, password=None,
                 token_name=None, token_value=None, verify_ssl=False, timeout=30):

        if host is None or user is None:
            raise ValueError("Proxmox VE host and user must be defined")

        from proxmoxer import ProxmoxAPI

        common_kwargs = dict(
            user=user,
            port=port,
            verify_ssl=verify_ssl,
            timeout=timeout,
        )

        if token_name is not None and token_value is not None:
            self.client = ProxmoxAPI(host, token_name=token_name, token_value=token_value, **common_kwargs)
        elif password is not None:
            self.client = ProxmoxAPI(host, password=password, **common_kwargs)
        else:
            raise ValueError(
                "Proxmox VE authentication failed: neither password nor token_name and token_value are defined")

    def get_version(self):
        return self.client.version.get()

    def get_nodes(self):
        return list(self.client.nodes.get())

    def get_vms(self, node=None):
        """
        Return a list of all guests (VMs and containers) of a node.
        Each guest dict gets a 'vm_type' attribute to distinguish qemu from lxc.
        """

        if node is None:
            raise ValueError("No node name provided")

        vms = list()
        for vm in self.client.nodes(node).qemu.get():
            vm["vm_type"] = "qemu"
            vms.append(vm)

        for vm in self.client.nodes(node).lxc.get():
            vm["vm_type"] = "lxc"
            vms.append(vm)

        return vms

    def get_vm_config(self, node=None, vm_id=None, vm_type=None):
        """
        Return the config of a single guest
        """

        if node is None or vm_id is None or vm_type is None:
            raise ValueError("node, vm_id and vm_type must be defined")

        if vm_type == "qemu":
            return self.client.nodes(node).qemu(str(vm_id)).config.get()

        if vm_type == "lxc":
            return self.client.nodes(node).lxc(str(vm_id)).config.get()

        raise ValueError(f"Unknown Proxmox guest type '{vm_type}'")

    def get_node_interfaces(self, node=None):
        """
        Return the network interface configuration of a node
        """

        if node is None:
            raise ValueError("No node name provided")

        return list(self.client.nodes(node).network.get())

    def get_storages(self, node=None):
        """
        Return the storage configuration visible on a node
        """

        if node is None:
            raise ValueError("No node name provided")

        return list(self.client.nodes(node).storage.get())
