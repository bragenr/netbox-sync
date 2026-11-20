# -*- coding: utf-8 -*-
#  Copyright (c) 2020 - 2026 netbox-sync team. All rights reserved.
#
#  netbox-sync.py
#
#  This work is licensed under the terms of the MIT license.
#  For a copy, see file LICENSE.txt included in this
#  repository or visit <https://opensource.org/licenses/MIT>.

"""
Unit tests for the Proxmox VE source.

The source handler is driven directly against a fake ProxmoxClient which serves
the same plain dicts/lists the proxmoxer API returns, so no Proxmox VE instance
is needed. The sync is verified on netbox-sync's own in-memory NetBoxInventory.
"""

import pytest

from module.common.logging import get_logger
from module.netbox.inventory import (
    NBCluster,
    NBDevice,
    NBIPAddress,
    NBManufacturer,
    NBSite,
    NBVirtualDisk,
    NBVM,
    NBInterface,
    NBVMInterface,
)
from module.sources.proxmox.connection import ProxmoxHandler
from module.sources.proxmox.disk import parse_disk_size

# sample data mirroring what the Proxmox VE API returns

NODES = [
    {
        "node": "pve01",
        "status": "online",
        "cpus": 8,
        "memory": 32 * 1024 * 1024 * 1024,
    },
]

NODE_INTERFACES = [
    {
        "iface": "vmbr0",
        "type": "bridge",
        "hwaddr": "3c:ec:ef:11:22:33",
        "cidr": "192.168.100.10/24",
    },
    {
        "iface": "lo",
        "type": "loopback",
    },
]

STORAGES = [
    {"storage": "local", "type": "dir", "content": "iso,backup", "shared": 0},
    {"storage": "ceph-pool", "type": "rbd", "content": "images,rootdir", "shared": 1},
]

# two qemu guests: one running with nets and disks, one template
QEMU_GUESTS = [
    {
        "vmid": 100,
        "name": "web-01",
        "status": "running",
        "maxmem": 4 * 1024 * 1024 * 1024,
        "maxdisk": 32 * 1024 * 1024 * 1024,
        "cpus": 2,
        "template": 0,
        "vm_type": "qemu",
    },
    {
        "vmid": 999,
        "name": "gold-image",
        "status": "stopped",
        "template": 1,
        "vm_type": "qemu",
    },
]

QEMU_VM_CONFIG = {
    "cores": 2,
    "memory": 4096,
    "net0": "virtio,bridge=vmbr0,firewall=1,hwaddr=BC:24:11:2F:2F:FF",
    "net1": "virtio=XX:XX:XX:XX:XX:XX,bridge=vmbr1",
    "ipconfig0": "gw=192.168.100.1,ip=192.168.100.100/24",
    "scsi0": "local-lvm:vm-100-disk-0,size=32G",
    "ide2": "local:iso/debian.iso,media=cdrom",
}

LXC_GUESTS = [
    {
        "vmid": 200,
        "name": "container-01",
        "status": "stopped",
        "maxmem": 1 * 1024 * 1024 * 1024,
        "maxdisk": 8 * 1024 * 1024 * 1024,
        "cpus": 1,
        "template": 0,
        "vm_type": "lxc",
    },
]

LXC_VM_CONFIG = {
    "cores": 1,
    "memory": 1024,
    "rootfs": "local-lvm:vm-200-disk-0,size=8G",
    "net0": "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:AA:BB:CC,ip=dhcp,ip6=dhcp,firewall=1",
}


class FakeProxmoxClient:
    """
    Serves the same dict/list structures as module.sources.proxmox.client.ProxmoxClient
    """

    def get_nodes(self):
        return NODES

    def get_vms(self, node=None):
        return QEMU_GUESTS + LXC_GUESTS

    def get_vm_config(self, node=None, vm_id=None, vm_type=None):
        if vm_type == "qemu":
            return QEMU_VM_CONFIG
        return LXC_VM_CONFIG

    def get_node_interfaces(self, node=None):
        return NODE_INTERFACES

    def get_storages(self, node=None):
        return STORAGES


@pytest.fixture
def proxmox_handler(inventory):
    """
    A Proxmox handler with a fake client and default settings, ready to apply()
    """

    handler = object.__new__(ProxmoxHandler)
    handler.inventory = inventory
    handler.name = "my-proxmox"
    handler.log = get_logger()
    handler.client = FakeProxmoxClient()

    from types import SimpleNamespace
    handler.settings = SimpleNamespace(
        enabled=True,
        site_name="proxmox",
        cluster_name=None,
        sync_nodes=True,
        sync_node_network=True,
        sync_guest_disks=True,
    )

    handler.set_source_tag()

    return handler


def get_inventory_items(inventory, object_type, **data):
    """
    Return all items of $object_type whose data matches $data
    """

    result = list()
    for this_object in inventory.get_all_items(object_type):
        match = True
        for key, value in data.items():
            if this_object.data.get(key) != value:
                match = False
                break
        if match is True:
            result.append(this_object)

    return result


def test_proxmox_cluster_and_site(proxmox_handler, inventory):

    proxmox_handler.apply()

    site = get_inventory_items(inventory, NBSite, name="proxmox")
    assert len(site) == 1

    cluster = get_inventory_items(inventory, NBCluster, name="Proxmox: my-proxmox")
    assert len(cluster) == 1
    assert cluster[0].data.get("type").data.get("name") == "proxmox"

    # shared storages are listed in the cluster comments, local storages are not
    assert "ceph-pool" in cluster[0].data.get("comments")
    assert "local" not in cluster[0].data.get("comments").split("ceph-pool")[0]
    assert "rbd" in cluster[0].data.get("comments")


def test_proxmox_nodes(proxmox_handler, inventory):

    proxmox_handler.apply()

    device = get_inventory_items(inventory, NBDevice, name="pve01")
    assert len(device) == 1
    assert device[0].data.get("status") == "active"

    # node platform and manufacturer
    assert device[0].data.get("platform").data.get("name") == "Proxmox VE"
    assert device[0].data.get("device_type").data.get("model") == "Proxmox VE Node"
    assert device[0].data.get("device_type").data.get("manufacturer").data.get("name") == "Proxmox"

    # node interfaces
    vmbr0 = get_inventory_items(inventory, NBInterface, device=device[0], name="vmbr0")
    assert len(vmbr0) == 1

    # interfaces without an address are synced but get no IP
    lo = get_inventory_items(inventory, NBInterface, device=device[0], name="lo")
    assert len(lo) == 1
    assert get_inventory_items(inventory, NBIPAddress, address="192.168.100.10/24") is not None
    assert len(get_inventory_items(inventory, NBIPAddress, address="192.168.100.10/24")) == 1


def test_proxmox_guests(proxmox_handler, inventory):

    proxmox_handler.apply()

    # template VMs are not synced
    assert get_inventory_items(inventory, NBVM, name="gold-image") == []

    # qemu guest
    vm = get_inventory_items(inventory, NBVM, name="web-01")
    assert len(vm) == 1

    vm = vm[0]
    assert vm.data.get("status") == "active"
    assert vm.data.get("vcpus") == 2.0
    assert vm.data.get("memory") == 4096
    assert vm.data.get("disk") == 32

    # VM interfaces
    eth0 = get_inventory_items(inventory, NBVMInterface, virtual_machine=vm, name="eth0")
    assert len(eth0) == 1
    assert eth0[0].data.get("mac_address") == "BC:24:11:2F:2F:FF"

    # interface IPs
    assert len(get_inventory_items(
        inventory, NBIPAddress, address="192.168.100.100/24", assigned_object_id=eth0[0])) == 1

    # VM disks, cdrom is skipped
    assert len(get_inventory_items(inventory, NBVirtualDisk, virtual_machine=vm)) == 1
    disk = get_inventory_items(inventory, NBVirtualDisk, virtual_machine=vm, name="web-01-scsi0")
    assert len(disk) == 1
    assert disk[0].data.get("size") == 32 * 1024

    # lxc guest
    ct = get_inventory_items(inventory, NBVM, name="container-01")
    assert len(ct) == 1
    assert ct[0].data.get("status") == "offline"
    assert ct[0].data.get("memory") == 1024
    assert get_inventory_items(
        inventory, NBVirtualDisk, virtual_machine=ct[0], name="container-01-rootfs")


def test_parse_disk_size():

    assert parse_disk_size("32G") == 32 * 1024
    assert parse_disk_size("8G") == 8 * 1024
    assert parse_disk_size("512M") == 512
    assert parse_disk_size("1T") == 1024 * 1024
    assert parse_disk_size(None) is None
    assert parse_disk_size("") is None
    assert parse_disk_size("123") is None


def test_proxmox_config_auth_validation(load_config):
    """
    Partial token definitions or missing auth must fail config validation
    instead of crashing the source during apply()
    """

    from module.sources.proxmox.config import ProxmoxConfig

    def parse_source(section: dict):
        content = "[netbox]\nurl = https://netbox.example.com\napi_token = xxx\n[source/my-pve]\n"
        content += "\n".join(f"{key} = {value}" for key, value in section.items())
        load_config(content)

        config = ProxmoxConfig()
        config.source_name = "my-pve"
        try:
            config.parse()
        except SystemExit:
            # failed validation exits the program, the test only cares
            # about the parsing result
            pass
        return config

    # only token_name defined -> validation must fail
    config = parse_source({
        "type": "proxmox",
        "host": "pve.example.com",
        "user": "root@pam",
        "token_name": "sync",
    })
    assert config._parsing_failed is True

    # token_name and token_value defined -> validation must pass
    config = parse_source({
        "type": "proxmox",
        "host": "pve.example.com",
        "user": "root@pam",
        "token_name": "sync",
        "token_value": "abcd-1234",
    })
    assert config._parsing_failed is False

    # password only -> validation must pass
    config = parse_source({
        "type": "proxmox",
        "host": "pve.example.com",
        "user": "root@pam",
        "password": "secret",
    })
    assert config._parsing_failed is False

    # no auth at all -> validation must fail
    config = parse_source({
        "type": "proxmox",
        "host": "pve.example.com",
        "user": "root@pam",
    })
    assert config._parsing_failed is True


def test_proxmox_string_api_values(proxmox_handler, inventory, monkeypatch):
    """
    The Proxmox API returns numbers as strings (lxc configs) and sometimes
    with decimals. The sync must not crash on those.
    """

    # lxc config with all string values and a decimal memory value
    monkeypatch.setattr(
        proxmox_handler.client, "get_vm_config",
        lambda node=None, vm_id=None, vm_type=None: {
            "cores": "4", "memory": "512.5",
            "rootfs": "local-lvm:vm-200-disk-0,size=8G",
        },
    )
    monkeypatch.setattr(
        proxmox_handler.client, "get_vms",
        lambda node=None: [{
            "vmid": "200", "name": "container-01", "status": "running",
            "maxmem": "1073741824", "maxdisk": "8589934592", "cpus": "1",
            "template": "0", "vm_type": "lxc",
        }],
    )

    proxmox_handler.apply()

    vm = get_inventory_items(inventory, NBVM, name="container-01")
    assert len(vm) == 1
    assert vm[0].data.get("vcpus") == 4.0
    assert vm[0].data.get("memory") == 512  # 512.5 MB rounded down, no crash

    disks = get_inventory_items(inventory, NBVirtualDisk, virtual_machine=vm[0])
    assert len(disks) == 1
    assert disks[0].data.get("size") == 8 * 1024

    # VMs marked as templates (also as string) are skipped
    monkeypatch.setattr(
        proxmox_handler.client, "get_vms",
        lambda node=None: [{
            "vmid": "500", "name": "gold-image", "status": "stopped",
            "template": "1", "vm_type": "qemu",
        }],
    )

    inv = proxmox_handler.inventory
    inv.base_structure = {}
    inv.source_list = []
    inv.init()

    proxmox_handler.apply()
    assert get_inventory_items(inventory, NBVM, name="gold-image") == []
