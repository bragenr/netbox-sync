# -*- coding: utf-8 -*-
#  Copyright (c) 2020 - 2026 netbox-sync team. All rights reserved.
#
#  netbox-sync.py
#
#  This work is licensed under the terms of the MIT license.
#  For a copy, see file LICENSE.txt included in this
#  repository or visit <https://opensource.org/licenses/MIT>.

from module.common.logging import get_logger
from module.common.support import normalize_mac_address
from module.sources.common.source_base import SourceBase
from module.sources.proxmox.client import ProxmoxClient
from module.sources.proxmox.config import ProxmoxConfig
from module.sources.proxmox.network import sync_vm_network
from module.sources.proxmox.disk import sync_vm_disks

log = get_logger()

from module.netbox.inventory import (
    NetBoxInventory,
    NBVM,
    NBSite,
    NBCluster,
    NBClusterType,
    NBDevice,
    NBDeviceType,
    NBDeviceRole,
    NBManufacturer,
    NBPlatform,
    NBVMInterface,
    NBInterface,
    NBIPAddress,
    NBVirtualDisk,
)

# NetBox scope type for sites
SCOPE_TYPE_SITE = "dcim.site"

# map Proxmox guest status to NetBox status
vm_status_map = {
    "running": "active",
    "stopped": "offline",
    "paused": "staged",
}


def to_int(value=None):
    """
    Robust conversion of a Proxmox API value to int.
    The API returns numbers as int or as string (lxc configs), sometimes with
    decimals (like memory: 512.5), which would crash a plain int() conversion.
    """

    if value in [None, ""]:
        return 0

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class ProxmoxHandler(SourceBase):

    source_type = "proxmox"
    source_tag = "proxmox"

    dependent_netbox_objects = [
        NBVM,
        NBCluster,
        NBSite,
        NBClusterType,
        NBDevice,
        NBDeviceType,
        NBDeviceRole,
        NBManufacturer,
        NBPlatform,
        NBIPAddress,
        NBVirtualDisk,
        NBVMInterface,
        NBInterface,
    ]

    def __init__(self, name=None):

        if name is None:
            raise ValueError(f"Invalid value for attribute 'name': '{name}'.")

        self.inventory = NetBoxInventory()
        self.name = name
        self.log = get_logger()
        self.client = None

        settings_handler = ProxmoxConfig()
        settings_handler.source_name = self.name
        self.settings = settings_handler.parse()

        self.set_source_tag()

        if self.settings.enabled is False:
            log.info(f"Source '{name}' is currently disabled. Skipping")
            return

        self.init_successful = True

    @classmethod
    def implements(cls, source_type):
        return source_type == "proxmox"

    def get_cluster_name(self):
        return self.settings.cluster_name or f"Proxmox: {self.name}"

    def apply(self):

        if self.client is None:

            if self.settings.token_name is not None and self.settings.token_value is not None:
                self.client = ProxmoxClient(
                    host=self.settings.host,
                    user=self.settings.user,
                    port=self.settings.port,
                    token_name=self.settings.token_name,
                    token_value=self.settings.token_value,
                    verify_ssl=self.settings.verify_ssl,
                )
            else:
                self.client = ProxmoxClient(
                    host=self.settings.host,
                    user=self.settings.user,
                    port=self.settings.port,
                    password=self.settings.password,
                    verify_ssl=self.settings.verify_ssl,
                )

        nodes = self.client.get_nodes()
        self.log.info(f"Connected to Proxmox VE, found {len(nodes)} nodes")

        # ---------------------------
        # main objects
        # ---------------------------

        site = self.inventory.add_update_object(
            NBSite,
            data={"name": self.settings.site_name},
            source=self,
        )

        cluster_type = self.inventory.add_update_object(
            NBClusterType,
            data={"name": "proxmox"},
            source=self,
        )

        manufacturer = self.inventory.add_update_object(
            NBManufacturer,
            data={"name": "Proxmox"},
            source=self,
        )

        node_device_type = self.inventory.add_update_object(
            NBDeviceType,
            data={
                "model": "Proxmox VE Node",
                "manufacturer": manufacturer,
            },
            source=self,
        )

        node_device_role = self.inventory.add_update_object(
            NBDeviceRole,
            data={
                "name": "Server",
                "vm_role": False,
            },
            source=self,
        )

        cluster = self.inventory.add_update_object(
            NBCluster,
            data={
                "name": self.get_cluster_name(),
                "type": cluster_type,
                "scope_type": SCOPE_TYPE_SITE,
                "scope_id": site,
                "comments": self.get_cluster_comments(nodes),
            },
            source=self,
        )

        # ---------------------------
        # node loop
        # ---------------------------

        node_devices = dict()

        if self.settings.sync_nodes is True:
            for node in nodes:

                node_name = node.get("node")

                # -------- device --------

                device = self.inventory.add_update_object(
                    NBDevice,
                    data={
                        "name": node_name,
                        "device_type": node_device_type,
                        "device_role": node_device_role,
                        "platform": self.get_platform("Proxmox VE"),
                        "status": "active" if node.get("status", "offline") == "online" else "offline",
                        "site": site,
                        "cluster": cluster,
                    },
                    source=self,
                )

                node_devices[node_name] = device

                # -------- node interfaces --------

                if self.settings.sync_node_network is True:
                    try:
                        self.sync_node_network(device, node_name)
                    except Exception as e:
                        self.log.error(f"Unable to sync network of node '{node_name}': {e}")

        # ---------------------------
        # guest loop
        # ---------------------------

        vm_count = 0

        for node in nodes:

            node_name = node.get("node")

            for guest in self.client.get_vms(node=node_name):

                # skip VM templates
                if to_int(guest.get("template")) == 1:
                    self.log.debug2(f"Skipping Proxmox VM template '{guest.get('name')}'")
                    continue

                guest_id = guest.get("vmid")

                try:
                    vm_config = self.client.get_vm_config(
                        node=node_name, vm_id=guest_id, vm_type=guest.get("vm_type")
                    )
                except Exception as e:
                    self.log.error(f"Unable to fetch config of guest '{guest.get('name')}' ({guest_id}): {e}")
                    continue

                # -------- VM --------

                guest_name = guest.get("name") or f"{node_name}-guest-{guest_id}"

                vm_data = {
                    "name": guest_name[:64],
                    "status": vm_status_map.get(guest.get("status"), "staged"),
                    "cluster": cluster,
                    "site": site,
                    "platform": self.get_platform("Proxmox VE" if guest.get("vm_type") == "qemu" else "LXC Container"),
                    "vcpus": float(to_int(vm_config.get("cores", guest.get("cpus"))) or 0),
                    "memory": to_int(vm_config.get("memory", to_int(guest.get("maxmem")) / 1024 / 1024)),
                }

                if node_devices.get(node_name) is not None:
                    vm_data["device"] = node_devices.get(node_name)

                vm_data = {key: value for key, value in vm_data.items() if value is not None}

                vm = self.inventory.add_update_object(
                    NBVM,
                    data=vm_data,
                    source=self,
                )

                vm_count += 1

                # -------- interfaces --------

                sync_vm_network(self, vm, guest, vm_config)

                # -------- disks --------

                if self.settings.sync_guest_disks is True:
                    total_disk_size_mb = sync_vm_disks(self, vm, guest, vm_config)

                    if total_disk_size_mb > 0:
                        vm.update(data={"disk": int(total_disk_size_mb / 1024)}, source=self)

        self.log.info(f"Proxmox VE source '{self.name}' synced {vm_count} guests")

    def get_platform(self, platform_name=None):

        return self.inventory.add_update_object(
            NBPlatform,
            data={"name": platform_name},
            source=self,
        )

    def sync_node_network(self, device, node_name):

        for node_interface in self.client.get_node_interfaces(node=node_name):

            interface_name = node_interface.get("iface")

            if interface_name is None:
                continue

            interface_address = node_interface.get("cidr") or node_interface.get("address")

            interface_data = {
                "name": interface_name[:64],
                "device": device,
                "enabled": True,
                "type": "virtual",
            }

            if node_interface.get("type") == "bridge":
                interface_data["description"] = "bridge"

            node_mac = normalize_mac_address(node_interface.get("hwaddr"))
            if node_mac is not None:
                interface_data["mac_address"] = node_mac

            interface = self.inventory.add_update_object(
                NBInterface,
                data=interface_data,
                source=self,
            )

            if interface_address is not None and "/" in interface_address:

                ip_data = {
                    "address": interface_address,
                    "assigned_object_type": "dcim.interface",
                    "assigned_object_id": interface,
                }

                existing_ip = next(
                    (ip for ip in self.inventory.get_all_items(NBIPAddress)
                     if ip.data.get("address") == interface_address),
                    None
                )

                if existing_ip is None:
                    self.inventory.add_object(NBIPAddress, data=ip_data, source=self)
                else:
                    existing_ip.update(ip_data, source=self)

    def get_cluster_comments(self, nodes=None):
        """
        Return a comment for the NetBox cluster listing the shared storages of this Proxmox VE instance
        """

        if nodes is None or len(nodes) == 0:
            return None

        shared_storages = dict()

        for node in nodes:

            try:
                storages = self.client.get_storages(node=node.get("node"))
            except Exception as e:
                self.log.error(f"Unable to fetch storages of node '{node.get('node')}': {e}")
                continue

            for storage in storages:

                if storage.get("shared") in [0, "0", None]:
                    continue

                shared_storages.setdefault(
                    storage.get("storage"),
                    {
                        "type": storage.get("type"),
                        "content": storage.get("content"),
                    }
                )

        if len(shared_storages) == 0:
            return None

        storage_lines = [
            f"* {name} (type: {data.get('type')}, content: {data.get('content')})"
            for name, data in shared_storages.items()
        ]

        return "Shared storages:\n" + "\n".join(storage_lines)
