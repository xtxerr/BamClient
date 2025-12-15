from __future__ import annotations

import argparse
import sys

from .settings import BamSettings
from .api import BamClientApi
from .utils import str_to_bool, canonicalize_cidr
from .errors import ApiError, NotFoundError
from .formatters import print_zone_records, print_reverse, print_network


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="BlueCat Address Manager REST v2 DNS/Network helper")

    p.add_argument("--host", help="BAM base URL or hostname (env: BAM_HOST)")
    p.add_argument("--user", help="BAM API username (env: BAM_USER)")
    p.add_argument("--password", help="BAM API password (env: BAM_PASSWORD)")
    p.add_argument("--config", help="Configuration name (env: BAM_CONFIG)")
    p.add_argument("--view", help="DNS view name (env: BAM_VIEW)")
    p.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    p.add_argument("--debug", action="store_true", help="Enable verbose HTTP debugging")

    sp = p.add_subparsers(dest="command", required=True)

    # list
    p_list = sp.add_parser("list", help="List DNS records / reverse mappings / network")
    g = p_list.add_mutually_exclusive_group(required=True)
    g.add_argument("--zone", help="DNS zone (e.g. example.com)")
    g.add_argument("--cidr", help="IP address or CIDR for reverse mappings (e.g. 192.0.2.1 or 192.0.2.0/24)")
    g.add_argument("--network", help="Network CIDR for network details (exact range lookup)")
    p_list.add_argument("--type", "-t", action="append", dest="types", choices=["A", "AAAA", "CNAME", "MX", "NS", "TXT"])

    # add
    p_add = sp.add_parser("add", help="Create DNS record or network object")
    g2 = p_add.add_mutually_exclusive_group(required=True)
    g2.add_argument("--zone", help="DNS zone (record creation)")
    g2.add_argument("--network", help="Network CIDR to create")
    p_add.add_argument("--name", help="Owner name (FQDN or relative to zone)")
    p_add.add_argument("--type", "-t", choices=["A", "AAAA", "CNAME", "MX", "NS", "TXT"])
    p_add.add_argument("--data", help="RR data / IP")
    p_add.add_argument("--ttl", type=int, default=3600)
    p_add.add_argument(
        "--with-reverse",
        nargs="?",
        const=True,
        default=True,
        type=str_to_bool,
        help="For A/AAAA: control reverseRecord (default: true)",
    )

    # delete
    p_del = sp.add_parser("delete", help="Delete DNS record or network object")
    g3 = p_del.add_mutually_exclusive_group(required=True)
    g3.add_argument("--id", type=int, help="ResourceRecord ID to delete")
    g3.add_argument("--network", help="Network CIDR to delete (range lookup)")
    g3.add_argument("--zone", help="DNS zone (delete record by name)")
    p_del.add_argument("--name", help="Owner name for delete-by-name")
    p_del.add_argument("--type", "-t", choices=["A", "AAAA", "CNAME", "MX", "NS", "TXT"])

    # update (DNS only)
    p_upd = sp.add_parser("update", help="Update an existing DNS record")
    p_upd.add_argument("--id", type=int, help="Record ID to update (preferred)")
    p_upd.add_argument("--zone", help="DNS zone (required when updating by name)")
    p_upd.add_argument("--name", help="Owner name (FQDN or relative to zone)")
    p_upd.add_argument("--type", "-t", choices=["A", "AAAA", "CNAME", "MX", "NS", "TXT"])
    p_upd.add_argument("--ttl", type=int)
    p_upd.add_argument("--data")
    p_upd.add_argument("--with-reverse", nargs="?", const=True, default=None, type=str_to_bool)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    settings = BamSettings.from_env().with_overrides(
        host=args.host,
        user=args.user,
        password=args.password,
        config=args.config,
        view=args.view,
        verify_tls=(False if args.insecure else None),
    )

    # ENV can force TLS off as well
    # (covered by BamSettings.from_env(); CLI --insecure overrides to False via with_overrides above)

    try:
        with BamClientApi(settings, debug=args.debug) as api:
            if args.command == "list":
                if args.cidr:
                    if args.types:
                        print("--type/-t can only be used with --zone, not with --cidr", file=sys.stderr)
                        return 1
                    rows = api.dns.list_reverse(args.cidr)
                    if not rows:
                        print(f"No reverse records found for {args.cidr}")
                        return 0
                    print_reverse(rows)
                    return 0

                if args.network:
                    if args.types:
                        print("--type/-t can only be used with --zone, not with --network", file=sys.stderr)
                        return 1
                    net = api.networks.get(args.network)
                    if not net:
                        print(f"No network found for {canonicalize_cidr(args.network)}")
                        return 0
                    print_network(net)
                    return 0

                # zone
                recs = api.dns.list_zone(args.zone, types=args.types)
                print_zone_records(recs)
                return 0

            if args.command == "add":
                if args.network:
                    res = api.networks.create(args.network, exist_ok=True)
                    if res.status == "exists":
                        print(f"Network {res.network.range} already exists with ID {res.network.id}")
                    else:
                        print(f"Created {res.network.type} {res.network.range} with ID {res.network.id} (block ID {res.block_id})")
                    return 0

                # zone record
                if not args.name or not args.type or not args.data:
                    print("add --zone requires --name, --type, --data", file=sys.stderr)
                    return 1
                rid = api.dns.add_record(
                    args.zone,
                    name=args.name,
                    rr_type=args.type,
                    data=args.data,
                    ttl=args.ttl,
                    with_reverse=args.with_reverse,
                )
                print(f"Created {args.type} {args.name} with ID {rid}")
                return 0

            if args.command == "delete":
                if args.network:
                    deleted = api.networks.delete(args.network, missing_ok=True)
                    if not deleted:
                        print(f"Network {canonicalize_cidr(args.network)} not found.")
                        return 0
                    print(f"Deleted network {canonicalize_cidr(args.network)}")
                    return 0

                if args.id:
                    api.dns.delete_record_by_id(args.id)
                    print(f"Deleted record ID {args.id}")
                    return 0

                # delete by name
                if not args.zone or not args.name:
                    print("delete by name requires --zone and --name", file=sys.stderr)
                    return 1
                rid = api.dns.delete_record(args.zone, name=args.name, rr_type=args.type)
                print(f"Deleted record ID {rid}")
                return 0

            if args.command == "update":
                record_id = args.id
                if record_id is None:
                    if not args.zone or not args.name:
                        print("update requires --id or (--zone and --name)", file=sys.stderr)
                        return 1
                    # resolve by name
                    # (use client via api.dns delete logic path)
                    # easiest: find then update
                    view = api._ensure_view()
                    z = api.client.resolve_zone(int(view["id"]), args.zone)
                    zone_abs = z.get("absoluteName") or z.get("name") or ""
                    fqdn, _ = api.dns.api.utils.normalize_owner_in_zone(args.name, zone_abs)  # not used; keep simple
                    rec = api.client.find_single_record_in_zone(z, fqdn=args.name, rr_type=args.type)
                    record_id = int(rec["id"])

                api.dns.update_record(
                    record_id=record_id,
                    ttl=args.ttl,
                    data=args.data,
                    rr_type_hint=args.type,
                    with_reverse=args.with_reverse,
                )
                print(f"Updated record ID {record_id}")
                return 0

        return 0

    except ApiError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

