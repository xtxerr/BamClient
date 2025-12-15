from __future__ import annotations
import json
import sys
import ipaddress
from typing import Dict, List, Optional, Any
import requests
from .errors import ApiError, ApiErrorDetails, map_http_error
from .utils import canonicalize_cidr, normalize_fqdn_for_match, normalize_owner_in_zone

class BlueCatV2Client:
    """
    Low-level client for BAM REST v2.
    - Raw dicts in/out
    - Raises typed ApiError subclasses on HTTP errors
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        verify: bool = True,
        timeout: float = 10.0,
        debug: bool = False,
        change_comment: Optional[str] = None,
    ) -> None:
        if not host.startswith("http"):
            host = "https://" + host
        self.base_url = host.rstrip("/") + "/api/v2"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.debug = debug

        self.session = requests.Session()
        self.session.verify = verify
        self.session.headers.update({"Accept": "application/hal+json"})

        self._basic_auth_header: Optional[str] = None
        self.change_comment = change_comment or "change by BamClien"

    # ---------------- HTTP ----------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers: Dict[str, str] = {}
        if self._basic_auth_header:
            headers["Authorization"] = self._basic_auth_header
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)

        if self.debug:
            print(f"[DEBUG] HTTP {method.upper()} {url}", file=sys.stderr)
            if params:
                print(f"[DEBUG]   params = {params}", file=sys.stderr)
            if json_body is not None:
                print(f"[DEBUG]   json   = {json.dumps(json_body, ensure_ascii=False)}", file=sys.stderr)

        try:
            resp = self.session.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError(
                f"{method.upper()} {url} failed: {exc}",
                details=ApiErrorDetails(url=url, method=method.upper()),
            ) from exc

        if self.debug:
            body_preview = (resp.text or "")[:500].replace("\n", "\\n")
            print(f"[DEBUG]   status = {resp.status_code}, body = {body_preview!r}", file=sys.stderr)

        if resp.status_code >= 400:
            status = resp.status_code
            code = None
            reason = None
            message = None
            detail: Any = None

            try:
                data = resp.json()
                if isinstance(data, dict):
                    code = data.get("code")
                    reason = data.get("reason")
                    message = data.get("message")
                    detail = data.get("detail") or data
                else:
                    detail = data
            except Exception:
                detail = resp.text.strip() or None

            exc_cls = map_http_error(status=status, code=code)
            raise exc_cls(
                f"{method.upper()} {url} failed with {status}: {message or detail}",
                details=ApiErrorDetails(
                    status=status,
                    code=code,
                    reason=reason,
                    message=message,
                    detail=detail,
                    url=url,
                    method=method.upper(),
                ),
            )

        return resp

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", path, params=params)

    def _post(self, path: str, *, params=None, json_body=None, extra_headers=None) -> requests.Response:
        return self._request("POST", path, params=params, json_body=json_body, extra_headers=extra_headers)

    def _put(self, path: str, *, json_body=None, extra_headers=None) -> requests.Response:
        return self._request("PUT", path, json_body=json_body, extra_headers=extra_headers)

    def _delete(self, path: str, *, extra_headers=None) -> requests.Response:
        return self._request("DELETE", path, extra_headers=extra_headers)

    # ---------------- Auth ----------------

    def login(self) -> None:
        resp = self._post("sessions", json_body={"username": self.username, "password": self.password})
        data = resp.json()
        basic = data.get("basicAuthenticationCredentials")
        if not basic:
            raise ApiError("Login response missing basicAuthenticationCredentials")
        self._basic_auth_header = f"Basic {basic}"
        self.session.headers["Authorization"] = self._basic_auth_header

    def logout(self) -> None:
        self._basic_auth_header = None
        self.session.headers.pop("Authorization", None)

    # ---------------- Helpers ----------------

    @staticmethod
    def _extract_collection(payload) -> List[Dict[str, Any]]:
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data", []) or []
        if isinstance(payload, list):
            return payload
        return []

    def _select_single(self, path: str, filter_expr: str, what: str) -> Dict[str, Any]:
        resp = self._get(path, params={"filter": filter_expr})
        items = self._extract_collection(resp.json())
        if not items:
            raise ApiError(f"{what} not found for filter {filter_expr!r}")
        if len(items) > 1:
            raise ApiError(f"{what} filter {filter_expr!r} returned {len(items)} results; please refine.")
        return items[0]

    # ---------------- Config/View/Zone ----------------

    def resolve_config(self, config_name: str) -> Dict[str, Any]:
        return self._select_single("configurations", f"name:'{config_name}'", "Configuration")

    def resolve_view(self, config_name: str, view_name: str) -> Dict[str, Any]:
        f = f"configuration.name:'{config_name}' and name:'{view_name}'"
        return self._select_single("views", f, "View")

    def resolve_zone(self, view_id: int, zone_abs_name: str) -> Dict[str, Any]:
        zone_abs = zone_abs_name.rstrip(".")
        f = f"view.id:{view_id} and absoluteName:'{zone_abs}'"
        return self._select_single("zones", f, "Zone")

    # ---------------- Blocks / Networks ----------------

    def resolve_block_by_range(self, config_name: str, block_cidr: str) -> Dict[str, Any]:
        block_cidr = canonicalize_cidr(block_cidr)
        f = f"configuration.name:'{config_name}' and range:'{block_cidr}'"
        params = {"filter": f, "limit": 2, "fields": "id,type,range"}
        resp = self._get("blocks", params=params)
        items = self._extract_collection(resp.json())
        if not items:
            raise ApiError(f"Block not found for range {block_cidr!r} in configuration {config_name!r}")
        if len(items) > 1:
            raise ApiError(f"Block range {block_cidr!r} returned {len(items)} results; please refine.")
        return items[0]

    def find_network_by_range(self, config_name: str, net_cidr: str) -> Optional[Dict[str, Any]]:
        net_cidr = canonicalize_cidr(net_cidr)
        f = f"configuration.name:'{config_name}' and range:'{net_cidr}'"
        params = {"filter": f, "limit": 2, "fields": "id,type,range,_links"}
        resp = self._get("networks", params=params)
        items = self._extract_collection(resp.json())
        if not items:
            return None
        if len(items) > 1:
            raise ApiError(f"Network range {net_cidr!r} returned {len(items)} results; please refine.")
        return items[0]

    def get_network(self, network_id: int, *, fields: Optional[str] = None) -> Dict[str, Any]:
        params = {"fields": fields} if fields else None
        resp = self._get(f"networks/{network_id}", params=params)
        return resp.json()

    def create_network_in_block(self, block_id: int, net_cidr: str) -> Dict[str, Any]:
        net_cidr = canonicalize_cidr(net_cidr)
        net = ipaddress.ip_network(net_cidr, strict=False)
        net_type = "IPv4Network" if net.version == 4 else "IPv6Network"
        headers = {"x-bcn-change-control-comment": self.change_comment}
        body = {"type": net_type, "range": net_cidr}
        resp = self._post(f"blocks/{block_id}/networks", json_body=body, extra_headers=headers)
        return resp.json()

    def delete_network(self, network_id: int) -> None:
        headers = {"x-bcn-change-control-comment": self.change_comment}
        self._delete(f"networks/{network_id}", extra_headers=headers)

    # ---------------- Addresses / Reverse ----------------

    def get_address_by_ip(self, config_name: str, ip_str: str) -> Optional[Dict[str, Any]]:
        f = f"address:'{ip_str}' and configuration.name:'{config_name}'"
        params = {"filter": f, "limit": 5, "fields": "id,address,name"}
        resp = self._get("addresses", params=params)
        items = (resp.json().get("data") or [])
        if not items:
            return None
        if len(items) > 1:
            raise ApiError(f"More than one address object for {ip_str} in {config_name}: ids={[i.get('id') for i in items]}")
        return items[0]

    def get_reverse_targets_for_address(self, address_id: int) -> List[Dict[str, Any]]:
        params = {"fields": "id,type,recordType,name,absoluteName,rdata,ttl,reverseRecord"}
        resp = self._get(f"addresses/{address_id}/resourceRecords", params=params)
        items = (resp.json().get("data") or [])
        results: List[Dict[str, Any]] = []
        for rr in items:
            r_type = (rr.get("type") or "").upper()
            r_rtype = (rr.get("recordType") or "").upper()
            rev_flag = bool(rr.get("reverseRecord"))

            if r_rtype == "PTR":
                target = rr.get("rdata") or rr.get("absoluteName") or rr.get("name")
                if target:
                    results.append({"id": rr.get("id"), "target": target, "ttl": rr.get("ttl")})
                continue

            if r_type == "HOSTRECORD" and rev_flag:
                target = rr.get("absoluteName") or rr.get("name") or rr.get("rdata")
                if target:
                    results.append({"id": rr.get("id"), "target": target, "ttl": rr.get("ttl")})

        return results

    def list_reverse_mappings_for_ip_or_cidr(self, config_name: str, cidr: str, *, max_hosts: int = 4096) -> List[Dict[str, Any]]:
        try:
            if "/" in cidr:
                net = ipaddress.ip_network(cidr, strict=False)
                host_count = max(net.num_addresses - 2, 0) if net.version == 4 else net.num_addresses
                if host_count > max_hosts:
                    raise ApiError(
                        f"Network {cidr!r} would expand to {host_count} host addresses; refusing to scan."
                    )
                ip_iter = net.hosts()
            else:
                ip_iter = [ipaddress.ip_address(cidr)]
        except ValueError as exc:
            raise ApiError(f"Invalid IP address or network {cidr!r}: {exc}") from exc

        results: List[Dict[str, Any]] = []
        for ip_obj in ip_iter:
            ip_str = str(ip_obj)
            addr = self.get_address_by_ip(config_name, ip_str)
            if not addr:
                continue
            addr_id = addr.get("id")
            if addr_id is None:
                continue
            rev_rrs = self.get_reverse_targets_for_address(int(addr_id))
            for rr in rev_rrs:
                results.append({"ip": addr.get("address", ip_str), "ptr": rr.get("target"), "id": rr.get("id"), "ttl": rr.get("ttl")})
        return results

    # ---------------- DNS Records ----------------

    def get_record_addresses(self, record_id: int) -> List[Dict[str, Any]]:
        resp = self._get(f"resourceRecords/{record_id}/addresses", params={"fields": "id,type,address"})
        return resp.json().get("data") or []

    def list_zone_records(self, zone: Dict[str, Any], rr_types: Optional[List[str]] = None, include_addresses: bool = True) -> List[Dict[str, Any]]:
        wanted = {t.upper() for t in (rr_types or [])} or {"A", "AAAA", "CNAME", "MX", "NS", "TXT"}
        params = {"fields": "id,type,name,absoluteName,ttl,recordType,rdata"}
        resp = self._get(f"zones/{zone['id']}/resourceRecords", params=params)
        items = resp.json().get("data") or []

        records: List[Dict[str, Any]] = []
        for rr in items:
            rr_id = rr.get("id")
            rr_res_type = rr.get("type")
            name = rr.get("absoluteName") or rr.get("name") or ""

            ttl_raw = rr.get("ttl")
            ttl_val: Optional[int]
            if isinstance(ttl_raw, int):
                ttl_val = ttl_raw
            else:
                try:
                    ttl_val = int(ttl_raw) if ttl_raw is not None else None
                except (TypeError, ValueError):
                    ttl_val = None

            if rr_res_type == "HostRecord":
                if not include_addresses:
                    if "A" in wanted or "AAAA" in wanted:
                        records.append({"id": rr_id, "type": "A", "name": name, "ttl": ttl_val, "data": None})
                    continue

                addrs = self.get_record_addresses(rr_id)
                for addr in addrs:
                    addr_type = addr.get("type")
                    ip = addr.get("address")
                    if not ip or not addr_type:
                        continue
                    rr_type = "A" if addr_type == "IPv4Address" else "AAAA" if addr_type == "IPv6Address" else None
                    if not rr_type or rr_type not in wanted:
                        continue
                    records.append({"id": rr_id, "type": rr_type, "name": name, "ttl": ttl_val, "data": ip})
                continue

            rec_type = (rr.get("recordType") or rr_res_type or "").upper()
            if rec_type == "ALIASRECORD" and rr.get("recordType"):
                rec_type = rr["recordType"].upper()
            if rec_type not in wanted:
                continue
            records.append({"id": rr_id, "type": rec_type, "name": name, "ttl": ttl_val, "data": rr.get("rdata")})
        return records

    def create_record_in_zone(self, zone: Dict[str, Any], rr_type: str, fqdn: str, label: str, data: str, *, ttl: int = 3600, with_reverse: bool = False) -> int:
        rr_type = rr_type.upper()
        fqdn = fqdn.rstrip(".")

        if rr_type in ("A", "AAAA"):
            ip = ipaddress.ip_address(data)
            addr_type = "IPv4Address" if ip.version == 4 else "IPv6Address"
            body = {
                "type": "HostRecord",
                "name": label or fqdn,
                "absoluteName": fqdn,
                "ttl": ttl,
                "reverseRecord": bool(with_reverse),
                "addresses": [{"type": addr_type, "address": str(ip)}],
            }
        else:
            body = {
                "type": "GenericRecord",
                "name": label or fqdn,
                "absoluteName": fqdn,
                "ttl": ttl,
                "recordType": rr_type,
                "rdata": data,
            }

        headers = {"x-bcn-change-control-comment": self.change_comment}
        resp = self._post(f"zones/{zone['id']}/resourceRecords", json_body=body, extra_headers=headers)
        new_id = resp.json().get("id")
        if new_id is None:
            raise ApiError(f"Create resourceRecord returned unexpected payload: {resp.json()!r}")
        return int(new_id)

    def get_resource_record(self, record_id: int) -> Dict[str, Any]:
        return self._get(f"resourceRecords/{record_id}").json()

    def delete_resource_record(self, record_id: int) -> None:
        headers = {"x-bcn-change-control-comment": self.change_comment}
        self._delete(f"resourceRecords/{record_id}", extra_headers=headers)

    def update_resource_record(
        self,
        record_id: int,
        *,
        new_ttl: Optional[int] = None,
        new_data: Optional[str] = None,
        rr_type_hint: Optional[str] = None,
        with_reverse: Optional[bool] = None,
    ) -> Dict[str, Any]:
        rec = self.get_resource_record(record_id)
        rec.pop("_links", None)
        rec.pop("_embedded", None)

        if new_ttl is not None:
            rec["ttl"] = new_ttl

        rtype = rec.get("type", "")

        if rtype == "HostRecord":
            if new_data is not None:
                ip = ipaddress.ip_address(new_data)
                addr_type = "IPv4Address" if ip.version == 4 else "IPv6Address"
                rec["addresses"] = [{"type": addr_type, "address": str(ip)}]
            if with_reverse is not None:
                rec["reverseRecord"] = bool(with_reverse)
        else:
            if new_data is not None:
                rr_type = (rr_type_hint or rec.get("recordType") or "").upper()
                if not rr_type:
                    t_upper = (rtype or "").upper()
                    if t_upper.endswith("RECORD"):
                        rr_type = t_upper[:-6]
                if not rr_type:
                    raise ApiError(f"update: cannot determine RR type for record {record_id}")
                rec["recordType"] = rr_type
                rec["rdata"] = new_data

        headers = {"x-bcn-change-control-comment": self.change_comment}
        return self._put(f"resourceRecords/{record_id}", json_body=rec, extra_headers=headers).json()

    def find_single_record_in_zone(self, zone: Dict[str, Any], fqdn: str, rr_type: Optional[str] = None, rr_types: Optional[List[str]] = None) -> Dict[str, Any]:
        if rr_types is None and rr_type is not None:
            rr_types = [rr_type]
        wanted = {t.upper() for t in rr_types} if rr_types else None

        zone_abs = zone.get("absoluteName") or zone.get("name") or ""
        target_fqdn, _ = normalize_owner_in_zone(fqdn, zone_abs)
        target = normalize_fqdn_for_match(target_fqdn)

        records = self.list_zone_records(zone, rr_types=None, include_addresses=False)
        matches: List[Dict[str, Any]] = []
        for r in records:
            name = r.get("name") or ""
            if normalize_fqdn_for_match(name) != target:
                continue
            r_t = (r.get("type") or "").upper()
            if wanted:
                if r_t == "A" and (("A" in wanted) or ("AAAA" in wanted)):
                    pass
                elif r_t not in wanted:
                    continue
            matches.append(r)

        if not matches:
            raise ApiError(f"No record found for name {fqdn!r} in zone {zone.get('absoluteName')!r}")
        if len(matches) > 1:
            ids = [m.get("id") for m in matches]
            raise ApiError(f"Multiple records named {fqdn!r} in zone {zone.get('absoluteName')!r}: ids={ids}")
        return matches[0]

