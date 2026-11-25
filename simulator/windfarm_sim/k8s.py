"""Keep the broker's CA certificate current.

Azure IoT Operations rotates the CA that signs the MQTT broker's certificate and
publishes the current one in a ConfigMap in its own namespace. A pod in another
namespace cannot mount that ConfigMap, so the deployment script copies it once,
and the copy goes stale at the next rotation.

``current_ca_file`` reads the ConfigMap through the Kubernetes API (the deployment
grants the simulator's service account read access to that one object). When the
live certificate differs from the mounted copy it is written to a temporary file
and that file is used instead. If anything fails, the mounted copy is used as
before.
"""
from __future__ import annotations

import json
import logging
import os
import ssl
import tempfile
import urllib.request
from pathlib import Path

log = logging.getLogger("windfarm.k8s")

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


def read_configmap_key(spec: str, timeout: float = 8.0) -> str | None:
    """Value of one key of a ConfigMap, given as "namespace/name/key". None when not running in a
    cluster, when access is denied or when the key does not exist."""
    try:
        namespace, name, key = spec.split("/", 2)
    except ValueError:
        log.warning("MQTT_CA_CONFIGMAP must be namespace/name/key, got %r", spec)
        return None
    host = os.environ.get("KUBERNETES_SERVICE_HOST")
    token_file = SERVICE_ACCOUNT_DIR / "token"
    if not host or not token_file.is_file():
        return None
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    if ":" in host:                                      # IPv6 literal
        host = f"[{host}]"
    url = f"https://{host}:{port}/api/v1/namespaces/{namespace}/configmaps/{name}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token_file.read_text(encoding='utf-8').strip()}",
        "Accept": "application/json"})
    try:
        context = ssl.create_default_context(cafile=str(SERVICE_ACCOUNT_DIR / "ca.crt"))
        with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
            body = json.load(response)
    except Exception as exc:                             # noqa: BLE001 - any failure means "keep the copy"
        log.info("could not read %s/%s from the cluster (%s); using the mounted CA", namespace, name, exc)
        return None
    value = (body.get("data") or {}).get(key)
    return value if isinstance(value, str) and "BEGIN CERTIFICATE" in value else None


def current_ca_file(mounted: str, configmap: str) -> str:
    """Path of the CA file to trust: the mounted copy, or a fresh copy when the cluster has a
    different one."""
    if not configmap:
        return mounted
    live = read_configmap_key(configmap)
    if live is None:
        return mounted
    try:
        if Path(mounted).is_file() and Path(mounted).read_text(encoding="utf-8").strip() == live.strip():
            return mounted
        fresh = Path(tempfile.gettempdir()) / "windfarm-broker-ca.crt"
        fresh.write_text(live, encoding="utf-8")
    except OSError as exc:
        log.warning("could not store the refreshed CA (%s); using the mounted copy", exc)
        return mounted
    log.warning("the broker CA in the cluster differs from the mounted copy; using the current one. "
                "Run edge/scripts/05-deploy-simulator.sh to renew the copy.")
    return str(fresh)
