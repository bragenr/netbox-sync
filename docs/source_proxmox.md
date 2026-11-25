# Source: proxmox

## Setup
You need to have a source section in your `settings.ini` file with following type:
```ini
type = proxmox
```

### Proxmox VE api
The source talks to the Proxmox VE REST API of your cluster. Authentication is possible either
with a user/password combination or with an API token (recommended).

To create an API token:
* Datacenter -> Permissions -> API Tokens
* make sure the token has at least `PVEAuditor` privileges on the `/` path
* disable "Privilege Separation" only if the token user itself has the required privileges

The token name has to be defined without the user part. A token for user `root@pam`
named `netbox-sync` is configured like this:
```ini
user = root@pam
token_name = netbox-sync
token_value = <token-uuid>
```

### Synced objects
* one NetBox site (name configurable via `site_name`, defaults to `proxmox`)
* one NetBox cluster with cluster type `proxmox`, scoped to the site. Shared storages
  of the Proxmox VE instance are listed in the cluster comments
* Proxmox nodes as NetBox devices (`sync_nodes`, including their network interfaces
  and IPs if `sync_node_network` is enabled)
* all VMs and LXC containers of all nodes as NetBox virtual machines with status,
  vCPUs, memory, platform, interfaces (including MAC addresses and IPs) and disks
  as NetBox virtual disks (`sync_guest_disks`)

### Options
| option | default | description |
|---|---|---|
| enabled | True | Enable or disable the source |
| host | - (mandatory) | Host name or IP of the Proxmox VE API endpoint |
| port | 8006 | TCP port of the Proxmox VE API endpoint |
| user | - (mandatory) | API user including realm, e.g. `root@pam` |
| password | - | Password for user/password authentication |
| token_name | - | API token name (together with token_value) |
| token_value | - | API token UUID (together with token_name) |
| verify_ssl | False | Verify the SSL certificate of the API endpoint |
| site_name | proxmox | NetBox site name for all objects of this source |
| cluster_name | Proxmox: \<source-name\> | NetBox cluster name for all guests of this source |
| sync_nodes | True | Sync Proxmox nodes as NetBox devices |
| sync_node_network | True | Sync node network interfaces and IPs |
| sync_guest_disks | True | Sync guest disks as NetBox virtual disks |
