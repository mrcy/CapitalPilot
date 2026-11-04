from __future__ import annotations

from ..base import PriceProvider, ProviderConfig
from ..http import HttpClient
from .bitpin import BitpinProvider
from .configurable import CustomAPIProvider, ServixProvider, StreamDataProvider
from .manual import ManualPriceProvider
from .tsetmc import TSETMCProvider

PROVIDER_CLASSES: dict[str, type[PriceProvider]] = {
    "tsetmc": TSETMCProvider, "bitpin": BitpinProvider, "streamdata": StreamDataProvider,
    "servix": ServixProvider, "custom_api": CustomAPIProvider, "manual": ManualPriceProvider,
}
# آدرس‌های ثابت و شناخته‌شده؛ بقیه فقط با https و allowlist
_BUILTIN_HTTP = {"tsetmc"}  # TSETMC در کلاینت‌های متن‌باز با http است و کلید ندارد


def build_provider(cfg: ProviderConfig) -> PriceProvider:
    cls = PROVIDER_CLASSES[cfg.kind]
    http = HttpClient(cfg.timeout, allow_http=cfg.kind in _BUILTIN_HTTP,
                      enforce_allowlist=cfg.kind in ("custom_api", "streamdata", "servix"))
    return cls(cfg, http)
