from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Optional, List
import os

@dataclass(frozen=True)
class BamSettings:
    host: str
    user: str
    password: str
    config: str
    view: str = "external"
    verify_tls: bool = True
    change_comment: Optional[str] = None
    blocks: List[str] = None  # space-separated CIDRs -> list[str]

    @staticmethod
    def from_env() -> "BamSettings":
        verify = os.getenv("BAM_VERIFY_TLS", "true").lower() not in ("false", "0", "no")
        blocks_str = os.getenv("BAM_BLOCKS", "") or ""
        return BamSettings(
            host=os.getenv("BAM_HOST", "").strip(),
            user=os.getenv("BAM_USER", "").strip(),
            password=os.getenv("BAM_PASSWORD", ""),
            config=os.getenv("BAM_CONFIG", "").strip(),
            view=os.getenv("BAM_VIEW", "external").strip() or "external",
            verify_tls=verify,
            change_comment=os.getenv("BAM_CHANGE_COMMENT") or None,
            blocks=blocks_str.split(),
        )

    def with_overrides(
        self,
        *,
        host: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        config: Optional[str] = None,
        view: Optional[str] = None,
        verify_tls: Optional[bool] = None,
        change_comment: Optional[str] = None,
        blocks: Optional[List[str]] = None,
    ) -> "BamSettings":
        return replace(
            self,
            host=self.host if host is None else host,
            user=self.user if user is None else user,
            password=self.password if password is None else password,
            config=self.config if config is None else config,
            view=self.view if view is None else view,
            verify_tls=self.verify_tls if verify_tls is None else verify_tls,
            change_comment=self.change_comment if change_comment is None else change_comment,
            blocks=self.blocks if blocks is None else blocks,
        )

