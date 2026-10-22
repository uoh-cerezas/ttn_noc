from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def iso_time(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


@dataclass
class Gateway:
    gateway_id: str
    display_name: str
    site: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    last_seen_at: datetime | None = None
    online: bool = False
    source: str = "ttn"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["last_seen_at"] = iso_time(self.last_seen_at)
        return result


@dataclass
class Sensor:
    device_id: str
    display_name: str
    site: str | None = None
    gateway_id: str | None = None
    last_seen_at: datetime | None = None
    battery_percent: float | None = None
    rssi: float | None = None
    snr: float | None = None
    source: str = "ttn"
    application_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    sensor_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["last_seen_at"] = iso_time(self.last_seen_at)
        return result


class NocState:
    def __init__(self) -> None:
        self.gateways: dict[str, Gateway] = {}
        self.sensors: dict[str, Sensor] = {}

    def upsert_gateway(self, gateway: Gateway) -> None:
        current = self.gateways.get(gateway.gateway_id)
        if current and gateway.last_seen_at is None:
            gateway.last_seen_at = current.last_seen_at
        if current and gateway.site is None:
            gateway.site = current.site
        if current and gateway.latitude is None:
            gateway.latitude = current.latitude
        if current and gateway.longitude is None:
            gateway.longitude = current.longitude
        if current and gateway.altitude is None:
            gateway.altitude = current.altitude
        self.gateways[gateway.gateway_id] = gateway

    def update_uplink(self, payload: dict[str, Any], site: str | None = None) -> None:
        ids = payload.get("end_device_ids") or {}
        device_id = ids.get("device_id")
        if not device_id:
            return
        application_id = ((ids.get("application_ids") or {}).get("application_id"))
        sensor_key = f"{application_id}/{device_id}" if application_id else device_id
        received_at = parse_time(payload.get("received_at")) or datetime.now(timezone.utc)
        decoded = ((payload.get("uplink_message") or {}).get("decoded_payload") or {})
        metadata = ((payload.get("uplink_message") or {}).get("rx_metadata") or [])
        first = metadata[0] if metadata else {}
        gateway_ids = first.get("gateway_ids") or {}
        gateway_id = gateway_ids.get("gateway_id")
        sensor = self.sensors.get(sensor_key) or Sensor(device_id, device_id)
        sensor.application_id = application_id or sensor.application_id
        sensor.site = site or sensor.site
        sensor.gateway_id = gateway_id or sensor.gateway_id
        sensor.last_seen_at = received_at
        sensor.rssi = first.get("rssi", sensor.rssi)
        sensor.snr = first.get("snr", sensor.snr)
        sensor.battery_percent = _battery(decoded, sensor.battery_percent)
        self.sensors[sensor_key] = sensor
        if gateway_id:
            gateway = self.gateways.get(gateway_id) or Gateway(gateway_id, gateway_id)
            gateway.last_seen_at = received_at
            gateway.online = True
            gateway.site = site or gateway.site
            self.gateways[gateway_id] = gateway


def _battery(decoded: dict[str, Any], previous: float | None) -> float | None:
    for key in ("battery_percent", "battery", "battery_level"):
        value = decoded.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return previous
