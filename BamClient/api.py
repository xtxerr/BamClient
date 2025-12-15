from __future__ import annotations
import ipaddress
from typing import Optional, List
from .settings import BamSettings
from .client import BlueCatV2Client
from .models import Network, DnsRecord, ReverseMapping, CreateNetworkResult
from .utils import canonicalize_cidr, parse_cidr_list, select_parent_block_for_network, normalize_owner_in_zone
from .errors import ApiError


class BamClientApi:
    """
    High-level facade.
    - context-managed login/logout
    - returns dataclasses (Network/DnsRecord/ReverseMapping)
    - exposes .networks and .dns services
    """

    def __init__(self, settings: BamSettings, *, debug: bool = False, timeout: float = 10.0) -> None:
        self.settings = settings
        self.client = BlueCatV2Client(
            host=settings.host,
            username=settings.user,
            password=settings.password,
            verify=settings.verify_tls,
            debug=debug,
            timeout=timeout,
            change_comment=settings.change_comment,
        )
        self._config: Optional[dict] = None
        self._view: Optional[dict] = None

        self.networks = _NetworksService(self)
        self.dns = _DnsService(self)

    def __enter__(self) -> "BamClientApi":
        if not self.settings.password:
            raise ApiError("BAM password missing (set BAM_PASSWORD or pass settings.password).")
        if not self.settings.host or not self.settings.user or not self.settings.config:
            raise ApiError("BAM settings incomplete (need host/user/config).")
        self.client.login()
        self._config = self.client.resolve_config(self.settings.config)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.client.logout()
        except Exception:
            pass

    @property
    def config_name(self) -> str:
        if not self._config:
            raise ApiError("API not initialized (use 'with BamClientApi(...) as api:').")
        return str(self._config["name"])

    def _ensure_view(self) -> dict:
        if self._view is None:
            self._view = self.client.resolve_view(self.config_name, self.settings.view)
        return self._view


class _NetworksService:
    def __init__(self, api: BamClientApi) -> None:
        self.api = api

    def get(self, cidr: str) -> Optional[Network]:
        net_cidr = canonicalize_cidr(cidr)
        item = self.api.client.find_network_by_range(self.api.config_name, net_cidr)
        if not item:
            return None
        net_id = int(item["id"])
        d = self.api.client.get_network(
            net_id,
            fields="id,type,range,name,gateway,defaultView,location,usage,userDefinedFields",
        )
        return _map_network(d)

    def create(self, cidr: str, *, exist_ok: bool = True) -> CreateNetworkResult:
        net_cidr = canonicalize_cidr(cidr)

        existing = self.api.client.find_network_by_range(self.api.config_name, net_cidr)
        if existing:
            net = self.get(net_cidr)
            if not net:
                # fallback minimal
                net = Network(id=int(existing["id"]), type=str(existing.get("type") or ""), range=str(existing.get("range") or net_cidr))
            block_id = _block_id_from_links(existing.get("_links") or {})
            return CreateNetworkResult(status="exists", network=net, block_id=block_id)

        blocks = parse_cidr_list(" ".join(self.api.settings.blocks or []))
        if not blocks:
            raise ApiError("create network requires BAM_BLOCKS (space-separated CIDRs) in settings.blocks or env BAM_BLOCKS.")

        net_obj = ipaddress.ip_network(net_cidr, strict=False)
        parent = select_parent_block_for_network(net_obj, blocks)
        block = self.api.client.resolve_block_by_range(self.api.config_name, str(parent))
        block_id = int(block["id"])

        created = self.api.client.create_network_in_block(block_id, net_cidr)
        net = _map_network(created)
        return CreateNetworkResult(status="created", network=net, block_id=block_id)

    def delete(self, cidr: str, *, missing_ok: bool = False) -> bool:
        net_cidr = canonicalize_cidr(cidr)
        item = self.api.client.find_network_by_range(self.api.config_name, net_cidr)
        if not item:
            if missing_ok:
                return False
            raise ApiError(f"Network {net_cidr} not found.")
        net_id = int(item["id"])
        self.api.client.delete_network(net_id)
        return True


class _DnsService:
    def __init__(self, api: BamClientApi) -> None:
        self.api = api

    def list_zone(self, zone: str, *, types: Optional[List[str]] = None) -> List[DnsRecord]:
        view = self.api._ensure_view()
        z = self.api.client.resolve_zone(int(view["id"]), zone)
        recs = self.api.client.list_zone_records(z, rr_types=types, include_addresses=True)
        return [DnsRecord(id=int(r["id"]), type=str(r["type"]), name=str(r["name"]), ttl=r.get("ttl"), data=r.get("data")) for r in recs]

    def add_record(
        self,
        zone: str,
        *,
        name: str,
        rr_type: str,
        data: str,
        ttl: int = 3600,
        with_reverse: bool = True,
    ) -> int:
        view = self.api._ensure_view()
        z = self.api.client.resolve_zone(int(view["id"]), zone)
        zone_abs = z.get("absoluteName") or z.get("name") or ""
        fqdn, label = normalize_owner_in_zone(name, zone_abs)
        wr = with_reverse if rr_type.upper() in ("A", "AAAA") else False
        return self.api.client.create_record_in_zone(z, rr_type=rr_type, fqdn=fqdn, label=label, data=data, ttl=ttl, with_reverse=wr)

    def delete_record_by_id(self, record_id: int) -> None:
        self.api.client.delete_resource_record(int(record_id))

    def delete_record(self, zone: str, *, name: str, rr_type: Optional[str] = None) -> int:
        view = self.api._ensure_view()
        z = self.api.client.resolve_zone(int(view["id"]), zone)
        zone_abs = z.get("absoluteName") or z.get("name") or ""
        fqdn, _ = normalize_owner_in_zone(name, zone_abs)
        rec = self.api.client.find_single_record_in_zone(z, fqdn=fqdn, rr_type=rr_type)
        rid = int(rec["id"])
        self.api.client.delete_resource_record(rid)
        return rid

    def update_record(
        self,
        *,
        record_id: int,
        ttl: Optional[int] = None,
        data: Optional[str] = None,
        rr_type_hint: Optional[str] = None,
        with_reverse: Optional[bool] = None,
    ) -> dict:
        return self.api.client.update_resource_record(
            int(record_id),
            new_ttl=ttl,
            new_data=data,
            rr_type_hint=rr_type_hint,
            with_reverse=with_reverse,
        )

    def list_reverse(self, cidr: str, *, max_hosts: int = 4096) -> List[ReverseMapping]:
        rows = self.api.client.list_reverse_mappings_for_ip_or_cidr(self.api.config_name, cidr, max_hosts=max_hosts)
        out: List[ReverseMapping] = []
        for r in rows:
            out.append(ReverseMapping(ip=str(r["ip"]), ptr=str(r["ptr"]), id=(int(r["id"]) if r.get("id") is not None else None), ttl=r.get("ttl")))
        return out


def _block_id_from_links(links: dict) -> Optional[int]:
    up = (links or {}).get("up", {}) or {}
    href = up.get("href")
    if not href or not isinstance(href, str):
        return None
    # expected: /api/v2/blocks/<id>
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except Exception:
        return None


def _map_network(d: dict) -> Network:
    dv = d.get("defaultView") or {}
    loc = d.get("location") or {}
    return Network(
        id=int(d["id"]),
        type=str(d.get("type") or ""),
        range=str(d.get("range") or ""),
        name=d.get("name"),
        gateway=d.get("gateway"),
        default_view=(dv.get("name") if isinstance(dv, dict) else None),
        location=(loc.get("name") if isinstance(loc, dict) else None),
        usage=(d.get("usage") if isinstance(d.get("usage"), dict) else None),
        user_defined_fields=(d.get("userDefinedFields") if isinstance(d.get("userDefinedFields"), dict) else None),
    )

