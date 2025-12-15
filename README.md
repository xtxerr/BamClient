# BamClient

## Abstract

**BamClient** is a command-line interface (CLI) and Python library that provides a simple integration layer for the **BlueCat Address Manager (BAM) RESTful v2 API**, with a focus on very simple **DNS resource record** and **network object** management. The project is aimed for shell, CI job, and Python-based usage with a clear separation between configuration, transport, and domain logic.

## Scope and Capabilities

The current implementation targets the following operational domains:

- **DNS management** (e.g., A/AAAA/CNAME/MX/NS/TXT record operations in a DNS view and zone)
- **Reverse mappings** for A/AAAA records (configurable behavior)
- **Simple Network object modifications** (list/create/delete networks within a defined set of permissible parent blocks)

## Installation

### Local installation
```
pip install .
```

(Optionally, use an editable install during development: pip install -e ..)

## Command-Line Interface Synopsis
```
$ BamClient --help
usage: BamClient [-h] [--host HOST] [--user USER] [--password PASSWORD]
                 [--config CONFIG] [--view VIEW] [--insecure] [--debug]
                 {list,add,delete,update} ...

BlueCat Address Manager REST v2 DNS/Network helper

positional arguments:
  {list,add,delete,update}
    list                List DNS records / reverse mappings / network
    add                 Create DNS record or network object
    delete              Delete DNS record or network object
    update              Update an existing DNS record

optional arguments:
  -h, --help            show this help message and exit
  --host HOST           BAM base URL or hostname (env: BAM_HOST)
  --user USER           BAM API username (env: BAM_USER)
  --password PASSWORD   BAM API password (env: BAM_PASSWORD)
  --config CONFIG       Configuration name (env: BAM_CONFIG)
  --view VIEW           DNS view name (env: BAM_VIEW)
  --insecure            Disable TLS certificate verification
  --debug               Enable verbose HTTP debugging
```

### add subcommand
```
$ BamClient add --help
usage: BamClient add [-h] (--zone ZONE | --network NETWORK) [--name NAME]
                     [--type {A,AAAA,CNAME,MX,NS,TXT}]
                     [--data DATA] [--ttl TTL]
                     [--with-reverse [WITH_REVERSE]]

optional arguments:
  -h, --help            show this help message and exit
  --zone ZONE           DNS zone (record creation)
  --network NETWORK     Network CIDR to create
  --name NAME           Owner name (FQDN or relative to zone)
  --type {A,AAAA,CNAME,MX,NS,TXT}, -t {A,AAAA,CNAME,MX,NS,TXT}
  --data DATA           RR data / IP
  --ttl TTL
  --with-reverse [WITH_REVERSE]
                        For A/AAAA: control reverseRecord (default: true)
```

### delete subcommand
```
$ /BamClient delete --help
usage: BamClient delete [-h] (--id ID | --network NETWORK | --zone ZONE) [--name NAME] [--type {A,AAAA,CNAME,MX,NS,TXT}]

optional arguments:
  -h, --help            show this help message and exit
  --id ID               ResourceRecord ID to delete
  --network NETWORK     Network CIDR to delete (range lookup)
  --zone ZONE           DNS zone (delete record by name)
  --name NAME           Owner name for delete-by-name
  --type {A,AAAA,CNAME,MX,NS,TXT}, -t {A,AAAA,CNAME,MX,NS,TXT}
```

### update subcommand
```
$ BamClient update --help
usage: BamClient update [-h] [--id ID] [--zone ZONE] [--name NAME] [--type {A,AAAA,CNAME,MX,NS,TXT}] [--ttl TTL] [--data DATA] [--with-reverse [WITH_REVERSE]]

optional arguments:
  -h, --help            show this help message and exit
  --id ID               Record ID to update (preferred)
  --zone ZONE           DNS zone (required when updating by name)
  --name NAME           Owner name (FQDN or relative to zone)
  --type {A,AAAA,CNAME,MX,NS,TXT}, -t {A,AAAA,CNAME,MX,NS,TXT}
  --ttl TTL
  --data DATA
  --with-reverse [WITH_REVERSE]
```

### list subcommand
```
$ BamClient list --help
usage: BamClient list [-h] (--zone ZONE | --cidr CIDR | --network NETWORK) [--type {A,AAAA,CNAME,MX,NS,TXT}]

optional arguments:
  -h, --help            show this help message and exit
  --zone ZONE           DNS zone (e.g. example.com)
  --cidr CIDR           IP address or CIDR for reverse mappings (e.g. 192.0.2.1 or 192.0.2.0/24)
  --network NETWORK     Network CIDR for network details (exact range lookup)
  --type {A,AAAA,CNAME,MX,NS,TXT}, -t {A,AAAA,CNAME,MX,NS,TXT}
```


### Network operations
```
$ BamClient list   --network 192.168.0.0/24
$ BamClient add    --network 2a02:1234:0:9998::/64
$ BamClient delete --network 2a02:1234:0:9998::/64
```

### DNS record listing and creation
```
$ BamClient list --zone example.com -t A -t AAAA
$ BamClient add  --zone example.com --name foo --type A --data 192.0.2.10
```

## Python API
```
from BamClient import BamSettings, BamClientApi
settings = BamSettings.from_env()

with BamClientApi(settings) as api:
    net = api.networks.get("192.168.0.1/24")
    print(net.range, net.id if net else None)

    api.networks.create("2a02:1234:0:9998::/64", exist_ok=True)
    api.networks.delete("2a02:1234:0:9998::/64", missing_ok=True)

    recs = api.dns.list_zone("example.com", types=["A", "AAAA"])
    print(len(recs))
```

## Configuration via Environment Variables

The CLI and Python settings loader support the following environment variables:
```
BAM_HOST — BAM base URL / hostname
BAM_USER — BAM API username
BAM_PASSWORD — BAM API password
BAM_CONFIG — BAM configuration name
BAM_VIEW — BAM DNS view name
BAM_CHANGE_COMMENT — change-comment metadata (if supported/used by the server-side workflow)
BAM_VERIFY_TLS=true|false — TLS certificate validation
```

## Network parent-block selection (BAM_BLOCKS)

For network creation via add --network, a parent block must be determinable. This is expressed as a whitespace-separated list of candidate CIDRs:
```
export BAM_BLOCKS="192.0.0.0/8 212.0.0.0/8 2a02:1234::/32"
```
Semantics: when --network <CIDR> is provided, the tool selects the most appropriate parent from BAM_BLOCKS (i.e., the block that contains the requested CIDR) and uses it as the parent object for creation. Consequently, BAM_BLOCKS must be defined for --network creation workflows.
