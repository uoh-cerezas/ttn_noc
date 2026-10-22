from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from .config import Settings
from .providers import MockProvider, TTNProvider


class NocService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.provider = MockProvider(self.settings) if self.settings.mode == "mock" else TTNProvider(self.settings)
        self.provider.start()

    def status(self) -> dict[str, Any]:
        gateways, sensors, error = self.provider.snapshot()
        for gateway in gateways:
            gateway["ttn_console_url"] = (
                f"{self.settings.console_base_url}/gateways/"
                f"{quote(str(gateway['gateway_id']), safe='')}"
            )
        for sensor in sensors:
            application_id = sensor.get("application_id")
            device_id = sensor.get("device_id")
            if application_id and device_id:
                sensor["ttn_application_url"] = (
                    f"{self.settings.console_base_url}/applications/"
                    f"{quote(str(application_id), safe='')}"
                )
                sensor["ttn_console_url"] = (
                    f"{self.settings.console_base_url}/applications/"
                    f"{quote(str(application_id), safe='')}/devices/{quote(str(device_id), safe='')}"
                )
        now = datetime.now(timezone.utc)
        for sensor in sensors:
            sensor["online"] = not _is_stale(sensor.get("last_seen_at"), self.settings.sensor_stale_minutes, now)
        return {
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "mode": self.settings.mode,
            "gateway_only": self.settings.gateway_only,
            "error": error,
            "summary": {
                "gateways_total": len(gateways),
                "gateways_online": sum(1 for item in gateways if item["online"]),
                "gateways_offline": sum(1 for item in gateways if not item["online"]),
                "sensors_total": len(sensors),
                "sensors_online": sum(1 for item in sensors if item["online"]),
                "sensors_offline": sum(1 for item in sensors if not item["online"]),
                "sensors_stale": sum(1 for item in sensors if _is_stale(item.get("last_seen_at"), self.settings.sensor_stale_minutes, now)),
            },
            "gateways": gateways,
            "sensors": sensors,
        }


def _is_stale(value: str | None, minutes: int, now: datetime) -> bool:
    if not value:
        return True
    try:
        last_seen = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now - last_seen).total_seconds() > minutes * 60
