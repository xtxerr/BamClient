from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal

@dataclass(frozen=True)
class Network:
    id: int
    type: str
    range: str
    name: Optional[str] = None
    gateway: Optional[str] = None
    default_view: Optional[str] = None
    location: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    user_defined_fields: Optional[Dict[str, Any]] = None

@dataclass(frozen=True)
class DnsRecord:
    id: int
    type: str
    name: str
    ttl: Optional[int]
    data: Optional[str]

@dataclass(frozen=True)
class ReverseMapping:
    ip: str
    ptr: str
    id: Optional[int] = None
    ttl: Optional[int] = None

@dataclass(frozen=True)
class CreateNetworkResult:
    status: Literal["created", "exists"]
    network: Network
    block_id: Optional[int] = None

