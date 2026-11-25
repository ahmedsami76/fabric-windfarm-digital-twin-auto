"""Simulator configuration, read from environment variables.

Every setting has a default that suits the demo, so the container runs
without any configuration beyond the MQTT connection settings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _env_int_or_none(name: str) -> int | None:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class SimConfig:
    # --- site and topics -------------------------------------------------
    site_file: str = "data/reference/site.json"
    topic_root: str = "contoso/windfarm"

    # --- publishing cadence (seconds) -------------------------------------
    telemetry_interval_s: float = 5.0
    weather_interval_s: float = 10.0
    registry_interval_s: float = 300.0
    heartbeat_interval_s: float = 60.0

    # --- randomisation ----------------------------------------------------
    # None means "pick a fresh random seed on every start".
    seed: int | None = None
    # climate: the wind follows the site climate shared with the history and the forecast
    # (season, time of day, weather systems). regime: a random mean inside the band below.
    wind_model: str = "climate"
    # Apply the standing conditions of site.json (worn gearbox on WT-07 and so on).
    standing_conditions: bool = True
    wind_mean: float = 9.0            # regime model only: long-run mean hub-height wind, m/s
    wind_regime_min: float = 6.5      # regime shifts stay inside this band so
    wind_regime_max: float = 12.5     # the farm is never dead calm for a demo
    ambient_mean_c: float = 18.0
    spontaneous_events_per_hour: float = 1.0   # site-wide; 0 disables

    # --- MQTT ---------------------------------------------------------------
    sink: str = "mqtt"                # mqtt | stdout
    mqtt_host: str = "aio-broker.azure-iot-operations.svc.cluster.local"
    mqtt_port: int = 18883
    mqtt_auth: str = "k8s-sat"        # k8s-sat | none | userpass
    mqtt_tls: bool = True
    mqtt_protocol: str = "v5"         # v5 (required for k8s-sat) | v311
    mqtt_ca_file: str = "/var/run/certs/ca.crt"
    # Where a fresh copy of the broker CA can be read when the mounted one has gone stale
    # (Azure IoT Operations rotates its CA). "namespace/configmap/key"; empty disables it.
    mqtt_ca_configmap: str = "azure-iot-operations/azure-iot-operations-aio-ca-trust-bundle/ca.crt"
    mqtt_sat_file: str = "/var/run/secrets/tokens/broker-sat"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_client_id: str = "windfarm-simulator"

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "SimConfig":
        d = cls()
        return cls(
            site_file=_env("SITE_FILE", d.site_file),
            topic_root=_env("TOPIC_ROOT", d.topic_root).strip("/"),
            telemetry_interval_s=_env_float("TELEMETRY_INTERVAL_S", d.telemetry_interval_s),
            weather_interval_s=_env_float("WEATHER_INTERVAL_S", d.weather_interval_s),
            registry_interval_s=_env_float("REGISTRY_INTERVAL_S", d.registry_interval_s),
            heartbeat_interval_s=_env_float("HEARTBEAT_INTERVAL_S", d.heartbeat_interval_s),
            seed=_env_int_or_none("SEED"),
            wind_model=_env("WIND_MODEL", d.wind_model).lower(),
            standing_conditions=_env_bool("STANDING_CONDITIONS", d.standing_conditions),
            wind_mean=_env_float("WIND_MEAN", d.wind_mean),
            wind_regime_min=_env_float("WIND_REGIME_MIN", d.wind_regime_min),
            wind_regime_max=_env_float("WIND_REGIME_MAX", d.wind_regime_max),
            ambient_mean_c=_env_float("AMBIENT_MEAN_C", d.ambient_mean_c),
            spontaneous_events_per_hour=_env_float(
                "SPONTANEOUS_EVENTS_PER_HOUR", d.spontaneous_events_per_hour
            ),
            sink=_env("SINK", d.sink).lower(),
            mqtt_host=_env("MQTT_HOST", d.mqtt_host),
            mqtt_port=int(_env("MQTT_PORT", str(d.mqtt_port))),
            mqtt_auth=_env("MQTT_AUTH", d.mqtt_auth).lower(),
            mqtt_tls=_env_bool("MQTT_TLS", d.mqtt_tls),
            mqtt_protocol=_env("MQTT_PROTOCOL", d.mqtt_protocol).lower(),
            mqtt_ca_file=_env("MQTT_CA_FILE", d.mqtt_ca_file),
            mqtt_ca_configmap=_env("MQTT_CA_CONFIGMAP", d.mqtt_ca_configmap),
            mqtt_sat_file=_env("MQTT_SAT_FILE", d.mqtt_sat_file),
            mqtt_username=_env("MQTT_USERNAME", d.mqtt_username),
            mqtt_password=_env("MQTT_PASSWORD", d.mqtt_password),
            mqtt_client_id=_env("MQTT_CLIENT_ID", d.mqtt_client_id),
            log_level=_env("LOG_LEVEL", d.log_level).upper(),
        )
