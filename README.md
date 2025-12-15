# BamClient

CLI + Python-API for BlueCat Address Manager REST v2 (DNS + Networks).

## Installation (local)
```bash
pip install .

## CLI

BamClient list --network 192.168.0.0/24
BamClient add  --network 2a02:1234:0:9998::/64
BamClient delete --network 2a02:1234:0:9998::/64

BamClient list --zone example.com -t A -t AAAA
BamClient add  --zone example.com --name foo --type A --data 192.0.2.10

## Python API

from BamClient import BamSettings, BamClientApi

settings = BamSettings.from_env()
with BamClientApi(settings) as api:
    net = api.networks.get("192.168.0.1/24")
    print(net.range, net.id if net else None)

    res = api.networks.create("2a02:1234:0:9998::/64", exist_ok=True)
    api.networks.delete("2a02:1234:0:9998::/64", missing_ok=True)

    recs = api.dns.list_zone("example.com", types=["A","AAAA"])
    print(len(recs))

## ENV vars
BAM_HOST, BAM_USER, BAM_PASSWORD, BAM_CONFIG, BAM_VIEW, BAM_CHANGE_COMMENT
BAM_VERIFY_TLS=true/false
BAM_BLOCKS="192.0.0.0/8 212.0.0.0/8 2a02:1234::/32" (for add --network)


