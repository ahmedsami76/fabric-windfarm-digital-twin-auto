"""MQTT connection shared by the simulator and the ``simctl`` command tool.

Inside the cluster the Azure IoT Operations broker requires TLS and a
Kubernetes service account token (SAT), presented through MQTT v5 enhanced
authentication with the method name ``K8S-SAT``. For local development the
link can also connect to a plain broker with no TLS or authentication.
"""
from __future__ import annotations

import json
import logging
import ssl
import threading
from pathlib import Path
from typing import Callable

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .config import SimConfig

log = logging.getLogger("windfarm.mqtt")

MessageHandler = Callable[[str, bytes], None]


class MqttLink:
    def __init__(self, cfg: SimConfig, client_id: str | None = None,
                 on_message: MessageHandler | None = None):
        self.cfg = cfg
        self.connected = threading.Event()
        self._subscriptions: list[str] = []
        self._on_message = on_message
        self._stopping = False
        self._v5 = cfg.mqtt_protocol != "v311"
        if cfg.mqtt_auth == "k8s-sat" and not self._v5:
            raise ValueError("MQTT_AUTH=k8s-sat requires MQTT_PROTOCOL=v5")

        kwargs = {"client_id": client_id or cfg.mqtt_client_id}
        if self._v5:
            kwargs["protocol"] = mqtt.MQTTv5
        else:
            kwargs["protocol"] = mqtt.MQTTv311
            kwargs["clean_session"] = True
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, **kwargs)
        self.client.on_connect = self._handle_connect
        self.client.on_disconnect = self._handle_disconnect
        self.client.on_message = self._handle_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        if cfg.mqtt_tls:
            ca = Path(cfg.mqtt_ca_file)
            if not ca.is_file():
                raise FileNotFoundError(f"broker CA certificate not found at {ca}")
            self.client.tls_set(ca_certs=str(ca), cert_reqs=ssl.CERT_REQUIRED,
                                tls_version=ssl.PROTOCOL_TLS_CLIENT)
        if cfg.mqtt_auth == "userpass":
            self.client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)

    # ------------------------------------------------------------------ #
    def _connect_properties(self) -> Properties | None:
        if self.cfg.mqtt_auth != "k8s-sat":
            return None
        token = Path(self.cfg.mqtt_sat_file).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError(f"service account token at {self.cfg.mqtt_sat_file} is empty")
        props = Properties(PacketTypes.CONNECT)
        props.AuthenticationMethod = "K8S-SAT"
        props.AuthenticationData = token.encode("utf-8")
        return props

    def _arm_connect(self) -> None:
        """Store connection settings; the network loop performs the actual connect.

        Called again after every disconnect so that a reconnect always presents
        the current service account token (Kubernetes rotates the mounted file).
        """
        if self._v5:
            self.client.connect_async(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=60,
                                      clean_start=True, properties=self._connect_properties())
        else:
            self.client.connect_async(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=60)

    def start(self) -> None:
        log.info("connecting to %s:%d (auth=%s tls=%s protocol=%s)", self.cfg.mqtt_host,
                 self.cfg.mqtt_port, self.cfg.mqtt_auth, self.cfg.mqtt_tls, self.cfg.mqtt_protocol)
        self._arm_connect()
        self.client.loop_start()

    def stop(self) -> None:
        self._stopping = True
        self.client.disconnect()
        self.client.loop_stop()

    def wait_connected(self, timeout: float) -> bool:
        return self.connected.wait(timeout)

    def subscribe(self, topic: str) -> None:
        if topic not in self._subscriptions:
            self._subscriptions.append(topic)
        if self.connected.is_set():
            self.client.subscribe(topic, qos=1)

    def publish(self, topic: str, payload: dict, retain: bool = False, qos: int = 1) -> bool:
        if not self.connected.is_set():
            return False
        info = self.client.publish(topic, json.dumps(payload, separators=(",", ":")),
                                   qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    # ------------------------------------------------------------------ #
    def _handle_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            log.error("broker refused the connection: %s", reason_code)
            return
        log.info("connected to broker")
        self.connected.set()
        for topic in self._subscriptions:
            client.subscribe(topic, qos=1)

    def _handle_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        was_connected = self.connected.is_set()
        self.connected.clear()
        if self._stopping:
            return
        if was_connected:
            log.warning("disconnected from broker: %s", reason_code)
        try:
            self._arm_connect()
        except (OSError, ValueError) as exc:
            log.error("cannot prepare reconnect: %s", exc)

    def _handle_message(self, client, userdata, msg) -> None:
        if self._on_message is not None:
            try:
                self._on_message(msg.topic, msg.payload)
            except Exception:  # a bad command must never kill the network loop
                log.exception("error while handling message on %s", msg.topic)
