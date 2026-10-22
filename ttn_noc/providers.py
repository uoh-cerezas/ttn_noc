from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # Optional for mock-only local tests.
    requests = None
try:
    import yaml
except ImportError:  # Optional until live TTN mode is used.
    yaml = None

from .config import Settings
from .state import Gateway, NocState, Sensor, parse_time

LOGGER = logging.getLogger(__name__)


class MockProvider:
    def __init__(self, settings: Settings) -> None:
        now = datetime.now(timezone.utc)
        self.state = NocState()
        self.state.upsert_gateway(Gateway(
            gateway_id="gw-rengo-01", display_name="Gateway Rengo 01", site="rengo",
            latitude=-34.406, longitude=-70.858, altitude=320,
            last_seen_at=now - timedelta(minutes=2), online=True, source="mock",
        ))
        self.state.upsert_gateway(Gateway(
            gateway_id="gw-sanfernando-01", display_name="Gateway San Fernando 01", site="sanfernando",
            latitude=-34.584, longitude=-70.991, altitude=340,
            last_seen_at=now - timedelta(minutes=48), online=False, source="mock",
        ))
        self.state.sensors["sensor-rengo-01"] = Sensor("sensor-rengo-01", "Sensor Rengo 01", "rengo", "gw-rengo-01", now - timedelta(minutes=3), 87, -81, 8.4, "mock")
        self.state.sensors["sensor-sanfernando-01"] = Sensor("sensor-sanfernando-01", "Sensor San Fernando 01", "sanfernando", "gw-sanfernando-01", now - timedelta(minutes=55), 42, -116, -12.2, "mock")

    def snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        return ([item.to_dict() for item in self.state.gateways.values()], [item.to_dict() for item in self.state.sensors.values()], None)

    def start(self) -> None:
        return None


class TTNProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state = NocState()
        self.sites = _load_sites(settings.sites_file)
        self.gateway_site = {
            gateway_id: site for site, data in self.sites.items() for gateway_id in data.get("gateway_ids", [])
        }
        self.device_site = {
            device_id: site for site, data in self.sites.items() for device_id in data.get("device_ids", [])
        }
        self.last_error: str | None = None
        self._mqtt = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._refresh_gateways()
        if self.settings.sensor_applications and self.settings.mqtt_username and self.settings.mqtt_password:
            self._start_mqtt()
        elif self.settings.sensor_applications:
            LOGGER.warning("TTN MQTT credentials not configured; sensor state will use API last_seen_at values")
        else:
            LOGGER.info("No sensor applications configured; sensor inventory is disabled")

    def snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        self._refresh_gateways()
        self._refresh_sensors()
        now = datetime.now(timezone.utc)
        gateways = []
        for gateway in self.state.gateways.values():
            if gateway.last_seen_at:
                gateway.online = now - gateway.last_seen_at <= timedelta(minutes=self.settings.gateway_stale_minutes)
            gateways.append(gateway.to_dict())
        sensors = []
        for sensor in self.state.sensors.values():
            sensors.append(sensor.to_dict())
        return gateways, sensors, self.last_error

    def _refresh_sensors(self) -> None:
        if requests is None or not self.settings.api_key or not self.settings.sensor_applications:
            return
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        sensor_errors: list[str] = []
        for application_id in self.settings.sensor_applications:
            try:
                page = 1
                limit = 100
                while True:
                    response = requests.get(
                        f"{self.settings.sensor_http_base_url}/api/v3/applications/{application_id}/devices",
                        headers=headers,
                        params={"limit": limit, "page": page, "field_mask": "ids,name,description,version_ids,locations,last_seen_at"},
                        timeout=10,
                    )
                    response.raise_for_status()
                    items = response.json().get("end_devices", [])
                    for item in items:
                        ids = item.get("ids") or {}
                        device_id = ids.get("device_id")
                        if not device_id:
                            continue
                        latitude, longitude, altitude = _device_location(item)
                        sensor_key = f"{application_id}/{device_id}"
                        current = self.state.sensors.get(sensor_key)
                        sensor = Sensor(
                            device_id=device_id,
                            display_name=item.get("name") or device_id,
                            site=self.device_site.get(device_id),
                            gateway_id=current.gateway_id if current else None,
                            last_seen_at=parse_time(item.get("last_seen_at")) or (current.last_seen_at if current else None),
                            battery_percent=current.battery_percent if current else None,
                            rssi=current.rssi if current else None,
                            snr=current.snr if current else None,
                            source="ttn",
                            application_id=application_id,
                            latitude=latitude if latitude is not None else (current.latitude if current else None),
                            longitude=longitude if longitude is not None else (current.longitude if current else None),
                            altitude=altitude if altitude is not None else (current.altitude if current else None),
                            sensor_type=_sensor_type(item) or (current.sensor_type if current else None),
                        )
                        self.state.sensors[sensor_key] = sensor
                    total = int(response.headers.get("X-Total-Count", "0") or 0)
                    if not items or len(items) < limit or (total and page * limit >= total):
                        break
                    page += 1
            except (requests.RequestException, ValueError) as error:
                sensor_errors.append(f"{application_id}: {error}")
        if sensor_errors:
            self.last_error = "Sensor refresh failed: " + "; ".join(sensor_errors)

    def _refresh_gateways(self) -> None:
        if requests is None:
            self.last_error = "requests is not installed"
            return
        if not self.settings.api_key:
            self.last_error = "TTN_API_KEY is not configured"
            return
        try:
            headers = {"Authorization": f"Bearer {self.settings.api_key}"}
            page = 1
            limit = 100
            while True:
                response = requests.get(
                    f"{self.settings.identity_http_base_url}/api/v3/gateways",
                    headers=headers,
                    params={"limit": limit, "page": page, "field_mask": "ids,name,antennas"},
                    timeout=10,
                )
                response.raise_for_status()
                items = response.json().get("gateways", [])
                for item in items:
                    ids = item.get("ids") or {}
                    gateway_id = ids.get("gateway_id")
                    if not gateway_id:
                        continue
                    display_name = item.get("name") or gateway_id
                    ignored = {value.casefold() for value in self.settings.ignored_gateways}
                    gateway_key = gateway_id.casefold()
                    display_key = display_name.casefold()
                    if any(pattern in gateway_key or pattern in display_key for pattern in ignored):
                        LOGGER.info("Ignoring configured gateway: %s (%s)", gateway_id, display_name)
                        self.state.gateways.pop(gateway_id, None)
                        continue
                    latitude, longitude, altitude = _gateway_location(item)
                    with self._lock:
                        self.state.upsert_gateway(Gateway(
                            gateway_id=gateway_id,
                            display_name=display_name,
                            site=self.gateway_site.get(gateway_id),
                            latitude=latitude,
                            longitude=longitude,
                            altitude=altitude,
                            last_seen_at=parse_time(item.get("last_seen_at") or item.get("status_received_at")),
                            online=False,
                        ))
                total = int(response.headers.get("X-Total-Count", "0") or 0)
                if not items or len(items) < limit or (total and page * limit >= total):
                    break
                page += 1
            for gateway in list(self.state.gateways.values()):
                self._refresh_gateway_connection(gateway, headers)
            self.last_error = None
        except (requests.RequestException, ValueError) as error:
            self.last_error = str(error)
            LOGGER.warning("TTN gateway refresh failed: %s", error)

    def _refresh_gateway_connection(self, gateway: Gateway, headers: dict[str, str]) -> None:
        """Refresh live connection state from the regional Gateway Server."""
        response = requests.get(
            f"{self.settings.cluster_http_base_url}/api/v3/gs/gateways/{gateway.gateway_id}/connection/stats",
            headers=headers,
            timeout=10,
        )
        if response.status_code == 404:
            # TTN returns 404 when the gateway has no active connection stats.
            gateway.online = False
            return
        response.raise_for_status()
        stats = response.json() or {}
        connected_at = parse_time(stats.get("connected_at"))
        disconnected_at = parse_time(stats.get("disconnected_at"))
        gateway.last_seen_at = parse_time(
            stats.get("last_status_received_at")
            or stats.get("last_uplink_received_at")
            or stats.get("connected_at")
        )
        gateway.online = bool(connected_at and (disconnected_at is None or disconnected_at <= connected_at))

    def _start_mqtt(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.last_error = "paho-mqtt is not installed"
            return
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)
        client.tls_set()
        topics = [(f"v3/{application_id}@{self.settings.tenant}/devices/+/up", 0) for application_id in self.settings.sensor_applications]
        client.on_connect = lambda client, userdata, flags, reason_code, properties=None: client.subscribe(topics)
        client.on_message = lambda client, userdata, message: self._on_message(message.payload)
        client.connect_async(self.settings.mqtt_host, 8883, 60)
        client.loop_start()
        self._mqtt = client

    def _on_message(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode("utf-8"))
            self.state.update_uplink(payload, self.device_site.get((payload.get("end_device_ids") or {}).get("device_id")))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            LOGGER.warning("Ignored malformed TTN uplink")


def _load_sites(path: str) -> dict[str, dict[str, Any]]:
    if yaml is None:
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return payload.get("sites", {})
    except (OSError, yaml.YAMLError):
        return {}


def _gateway_location(item: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Return the first configured antenna location from a TTN gateway."""
    for antenna in item.get("antennas") or []:
        location = antenna.get("location") or {}
        latitude = _number(location.get("latitude"))
        longitude = _number(location.get("longitude"))
        if latitude is not None and longitude is not None:
            return latitude, longitude, _number(location.get("altitude"))
    return None, None, None


def _sensor_type(item: dict[str, Any]) -> str | None:
    """Build a compact sensor type from TTN device metadata."""
    description = str(item.get("description") or "").strip()
    if description:
        return description
    version_ids = item.get("version_ids") or {}
    brand = str(version_ids.get("brand_id") or "").strip()
    model = str(version_ids.get("model_id") or "").strip()
    if brand and model:
        return f"{brand.title()} {model.upper()}"
    return model or brand or None


def _device_location(item: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Return the first configured location from an end device's location map."""
    locations = item.get("locations") or {}
    if isinstance(locations, dict):
        candidates = locations.values()
    elif isinstance(locations, list):
        candidates = locations
    else:
        candidates = []
    for location in candidates:
        if not isinstance(location, dict):
            continue
        latitude = _number(location.get("latitude"))
        longitude = _number(location.get("longitude"))
        if latitude is not None and longitude is not None:
            return latitude, longitude, _number(location.get("altitude"))
    return None, None, None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
