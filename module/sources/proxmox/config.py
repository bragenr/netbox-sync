# -*- coding: utf-8 -*-
#  Copyright (c) 2020 - 2026 netbox-sync team. All rights reserved.
#
#  netbox-sync.py
#
#  This work is licensed under the terms of the MIT license.
#  For a copy, see file LICENSE.txt included in this
#  repository or visit <https://opensource.org/licenses/MIT>.

from module.common.logging import get_logger
from module.config import source_config_section_name
from module.config.base import ConfigBase
from module.config.option import ConfigOption

log = get_logger()


class ProxmoxConfig(ConfigBase):

    section_name = source_config_section_name
    source_name_example = "my-proxmox-example"

    def __init__(self):
        self.options = [

            ConfigOption(
                "enabled",
                bool,
                default_value=True,
                description="Enable or disable the Proxmox VE source."
            ),

            ConfigOption(
                "type",
                str,
                default_value="proxmox",
                description="Source type identifier. Must remain 'proxmox'."
            ),

            ConfigOption(
                "host",
                str,
                mandatory=True,
                description="Host name or IP address of the Proxmox VE API endpoint.",
            ),

            ConfigOption(
                "port",
                int,
                default_value=8006,
                description="TCP port of the Proxmox VE API endpoint."
            ),

            ConfigOption(
                "user",
                str,
                mandatory=True,
                description="User to authenticate against the Proxmox VE API, including realm. Example: root@pam"
            ),

            ConfigOption(
                "password",
                str,
                sensitive=True,
                description="Password for user/password authentication. Not needed if token_name and token_value are defined."
            ),

            ConfigOption(
                "token_name",
                str,
                description="API token name used for token authentication. Has to be defined together with token_value."
            ),

            ConfigOption(
                "token_value",
                str,
                sensitive=True,
                description="API token UUID used for token authentication. Has to be defined together with token_name."
            ),

            ConfigOption(
                "verify_ssl",
                bool,
                default_value=False,
                description="Verify the SSL certificate of the Proxmox VE API endpoint."
            ),

            ConfigOption(
                "site_name",
                str,
                default_value="proxmox",
                description="Name of the NetBox site all Proxmox objects created by this source will be assigned to."
            ),

            ConfigOption(
                "cluster_name",
                str,
                description="Name of the NetBox cluster all Proxmox guests of this source will be assigned to. Defaults to 'Proxmox: <source-name>'"
            ),

            ConfigOption(
                "sync_nodes",
                bool,
                default_value=True,
                description="Sync Proxmox nodes as NetBox devices."
            ),

            ConfigOption(
                "sync_node_network",
                bool,
                default_value=True,
                description="Sync the network interfaces and IPs of Proxmox nodes. Only used if sync_nodes is enabled."
            ),

            ConfigOption(
                "sync_guest_disks",
                bool,
                default_value=True,
                description="Sync the disks of Proxmox guests as NetBox virtual disks."
            ),
        ]

        super().__init__()

    def validate_options(self):
        """
        Ensure the configured authentication is complete: either an API token
        (token_name and token_value) or a password has to be defined.
        """

        get = lambda key: self.get_option_by_name(key).value

        token_name = get("token_name")
        token_value = get("token_value")
        password = get("password")

        if (token_name is None) != (token_value is None):
            self.set_validation_failed()
            log.error("Config options 'token_name' and 'token_value' in "
                      f"'source.{getattr(self, 'source_name', None)}' must be defined together")

        if token_name is None and password is None:
            self.set_validation_failed()
            log.error("Config options 'password' or 'token_name' and 'token_value' in "
                      f"'source.{getattr(self, 'source_name', None)}' are undefined. "
                      "At least one authentication method has to be defined")
