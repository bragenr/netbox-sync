# -*- coding: utf-8 -*-
#  Copyright (c) 2020 - 2026 netbox-sync team. All rights reserved.
#
#  netbox-sync.py
#
#  This work is licensed under the terms of the MIT license.
#  For a copy, see file LICENSE.txt included in this
#  repository or visit <https://opensource.org/licenses/MIT>.

from module.common.logging import get_logger
from module.netbox.inventory import NBVirtualDisk

log = get_logger()

# config keys of a guest config which define a disk or a container mount point
disk_config_keys = ["ide", "sata", "scsi", "virtio", "efidisk", "rootfs", "mp", "unused"]


def parse_disk_size(size=None):
    """
    Convert the size definition of a Proxmox disk (like 32G) into MB

    Returns
    -------
    int: disk size in MB, None if size is undefined or unparsable
    """

    if size is None:
        return None

    multipliers = {
        "K": 1 / 1024,
        "M": 1,
        "G": 1024,
        "T": 1024 * 1024,
        "P": 1024 * 1024 * 1024,
    }

    size = str(size).strip()

    if size[-1:].upper() not in multipliers:
        return None

    try:
        size_mb = round(int(size[:-1]) * multipliers[size[-1:].upper()])
    except ValueError:
        return None

    return int(size_mb)


def get_guest_disks(vm_config=None):
    """
    Collect all disks and mount points of a guest config

    Returns
    -------
    dict: config key (like scsi0) mapped to a tuple of (storage, size in MB)
    """

    disks = dict()

    if vm_config is None:
        return disks

    for config_key, config_value in vm_config.items():

        if config_key == "rootfs":
            key_prefix = "rootfs"
        elif any(config_key.startswith(x) and config_key[len(x):].isdigit() for x in disk_config_keys):
            key_prefix = next(x for x in disk_config_keys if config_key.startswith(x) and
                               config_key[len(x):].isdigit())
        else:
            continue

        disk_config = {}
        for part in str(config_value).split(","):
            key, _, value = part.partition("=")
            disk_config[key.strip()] = value.strip()

        storage = None
        if key_prefix != "rootfs" and ":" in str(config_value):
            storage = str(config_value).split(":", 1)[0]

        disk_size_mb = parse_disk_size(disk_config.get("size"))

        if disk_size_mb is None:
            continue

        disks[config_key] = (storage, disk_size_mb)

    return disks


def sync_vm_disks(handler, vm, guest, vm_config):
    """
    Sync Proxmox guest disks to NetBox virtual disks
    """

    inventory = handler.inventory

    total_disk_size_mb = 0

    for config_key, (storage, disk_size_mb) in get_guest_disks(vm_config).items():

        total_disk_size_mb += disk_size_mb

        disk_name = f"{vm.data.get('name')}-{config_key}"[:64]

        disk_data = {
            "name": disk_name,
            "virtual_machine": vm,
            "size": disk_size_mb,
            "description": f"storage: {storage} ({guest.get('vm_type')})" if storage is not None else guest.get("vm_type"),
        }

        existing_disk = None

        for disk in inventory.get_all_items(NBVirtualDisk):
            if (
                disk.data.get("name") == disk_name
                and disk.data.get("virtual_machine") == vm
            ):
                existing_disk = disk
                break

        if existing_disk is None:
            inventory.add_object(NBVirtualDisk, data=disk_data, source=handler)
        else:
            existing_disk.update(disk_data, source=handler)

    return total_disk_size_mb
