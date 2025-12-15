from __future__ import annotations
from typing import Iterable, Optional
from .models import Network, DnsRecord, ReverseMapping


def print_zone_records(records: Iterable[DnsRecord]) -> None:
    recs = list(records)
    if not recs:
        print("No records found.")
        return
    print(f"{'ID':>8}  {'TYPE':<6}  {'TTL':>6}  {'NAME':<50}  DATA")
    print("-" * 120)
    for r in recs:
        ttl_str = str(r.ttl) if r.ttl is not None else "-"
        print(f"{r.id:8d}  {r.type:<6}  {ttl_str:>6}  {r.name:<50}  {r.data or ''}")


def print_reverse(rows: Iterable[ReverseMapping]) -> None:
    items = list(rows)
    if not items:
        print("No reverse records found.")
        return
    print(f"{'IP':<39}  {'PTR-NAME':<60}  {'TTL':>6}  {'ID':>10}")
    print("-" * 120)
    for r in items:
        ttl_str = str(r.ttl) if r.ttl is not None else "-"
        rid = str(r.id) if r.id is not None else ""
        print(f"{r.ip:<39}  {(r.ptr or ''):<60}  {ttl_str:>6}  {rid:>10}")


def print_network(net: Optional[Network]) -> None:
    if not net:
        print("No network found.")
        return

    usage = net.usage or {}
    assigned = usage.get("assigned")
    unassigned = usage.get("unassigned")
    total = usage.get("total")

    def _fmt(v) -> str:
        return str(v) if isinstance(v, int) else "-"

    print(
        f"{'ID':>10}  {'TYPE':<10}  {'RANGE':<43}  {'NAME':<30}  "
        f"{'GATEWAY':<39}  {'VIEW':<16}  {'ASS':>6}  {'UNASS':>6}  {'TOTAL':>6}"
    )
    print("-" * 140)
    print(
        f"{net.id:10d}  "
        f"{net.type:<10}  "
        f"{net.range:<43}  "
        f"{(net.name or ''):<30}  "
        f"{(net.gateway or ''):<39}  "
        f"{(net.default_view or ''):<16}  "
        f"{_fmt(assigned):>6}  "
        f"{_fmt(unassigned):>6}  "
        f"{_fmt(total):>6}"
    )

