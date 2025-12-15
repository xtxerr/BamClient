from __future__ import annotations
import argparse
import ipaddress
from typing import List, Tuple, Optional
from .errors import ApiError

def str_to_bool(value: str) -> bool:
    if isinstance(value, bool):
        return value
    v = value.lower()
    if v in ("true", "t", "yes", "y", "1"):
        return True
    if v in ("false", "f", "no", "n", "0"):
        return False
    raise argparse.ArgumentTypeError("expected boolean value (true/false)")

def normalize_owner_in_zone(owner: str, zone_abs: str) -> tuple[str, str]:
    z = zone_abs.rstrip(".")
    n = owner.rstrip(".")
    if not n:
        raise ValueError("Empty owner name is not allowed")

    if n == z:
        return z, ""
    if n.endswith("." + z):
        label = n[: -(len(z) + 1)]
        return n, label
    label = n
    fqdn = f"{label}.{z}" if z else label
    return fqdn, label

def normalize_fqdn_for_match(name: str) -> str:
    return (name or "").rstrip(".").lower()

def canonicalize_cidr(cidr: str) -> str:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise ApiError(f"Invalid CIDR {cidr!r}: {exc}")
    return str(net)

def parse_cidr_list(value: str) -> List[ipaddress._BaseNetwork]:
    nets: List[ipaddress._BaseNetwork] = []
    for token in (value or "").split():
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError as exc:
            raise ApiError(f"Invalid CIDR in BAM_BLOCKS: {token!r} ({exc})")
    return nets

def select_parent_block_for_network(
    net: ipaddress._BaseNetwork,
    blocks: List[ipaddress._BaseNetwork],
) -> ipaddress._BaseNetwork:
    candidates = [b for b in blocks if b.version == net.version and net.subnet_of(b)]
    if not candidates:
        raise ApiError(
            f"No configured block contains network {net}. "
            "Set BAM_BLOCKS (space-separated CIDRs) to include a parent block."
        )
    candidates.sort(key=lambda b: b.prefixlen, reverse=True)
    return candidates[0]

