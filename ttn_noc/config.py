from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str = os.getenv("NOC_MODE", "mock").lower()
    gateway_only: bool = os.getenv("NOC_GATEWAY_ONLY", "false").lower() in {"1", "true", "yes", "on"}
    region: str = os.getenv("TTN_REGION", "eu1")
    identity_region: str = os.getenv("TTN_IDENTITY_REGION", "eu1")
    tenant: str = os.getenv("TTN_TENANT", "ttn")
    application_id: str = os.getenv("TTN_APPLICATION_ID", "")
    sensor_applications: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv("TTN_SENSOR_APPLICATIONS", "").split(",")
        if value.strip()
    )
    api_key: str = os.getenv("TTN_API_KEY", "").strip()
    mqtt_username: str = os.getenv("TTN_MQTT_USERNAME", "").strip()
    mqtt_password: str = os.getenv("TTN_MQTT_PASSWORD", "").strip()
    gateway_stale_minutes: int = int(os.getenv("NOC_GATEWAY_STALE_MINUTES", "15"))
    sensor_stale_minutes: int = int(os.getenv("NOC_SENSOR_STALE_MINUTES", "30"))
    ignored_gateways: frozenset[str] = frozenset(
        value.strip()
        for value in os.getenv("NOC_IGNORED_GATEWAYS", "").split(",")
        if value.strip()
    )
    sites_file: str = os.getenv("NOC_SITES_FILE", "config/sites.yaml")
    port: int = int(os.getenv("NOC_PORT", "8060"))

    @property
    def identity_http_base_url(self) -> str:
        return f"https://{self.identity_region}.cloud.thethings.network"

    @property
    def http_base_url(self) -> str:
        """Backward-compatible alias for the Identity Server URL."""
        return self.identity_http_base_url

    @property
    def cluster_http_base_url(self) -> str:
        return f"https://{self.region}.cloud.thethings.network"

    @property
    def sensor_http_base_url(self) -> str:
        # End-device registry requests are served by the Identity Server,
        # just like the gateway inventory endpoint.
        return self.identity_http_base_url

    @property
    def console_base_url(self) -> str:
        configured = os.getenv("TTN_CONSOLE_BASE_URL", "").strip()
        return configured.rstrip("/") if configured else f"{self.cluster_http_base_url}/console"

    @property
    def mqtt_host(self) -> str:
        return f"{self.region}.cloud.thethings.network"

    @property
    def mqtt_topic(self) -> str:
        return f"v3/{self.application_id}@{self.tenant}/devices/+/up"
