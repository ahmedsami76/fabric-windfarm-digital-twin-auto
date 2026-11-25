"""Names and settings: one suffix of three characters for a deployment, and the settings file made from it.

The suffix is chosen when a deployment is started and written into that deployment's settings,
.deploy/<suffix>/demo.env (deployments.py). Every later run reads it there, so a plan, its apply and every
resume speak of the same resources.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
# Names that have to be unique beyond the demo's own workspace, with the name the guides suggest.
SUFFIXED = {
    "RESOURCE_GROUP": "rg-windfarm-edge",
    "VM_NAME": "vm-windfarm-edge",
    "CLUSTER_NAME": "arc-windfarm-edge",
    "AIO_INSTANCE_NAME": "aio-windfarm",
    "CUSTOM_LOCATION_NAME": "cl-windfarm-edge",
    "SCHEMA_REGISTRY_NAME": "sr-windfarm",
    "SCHEMA_REGISTRY_NAMESPACE": "sr-windfarm-ns",
    "DEVICE_REGISTRY_NAMESPACE_NAME": "adr-windfarm",
    "FABRIC_WORKSPACE_NAME": "WindFarmDigitalTwin",
}
# A storage account takes lower-case letters and digits only, 3 to 24 of them.
STORAGE = ("STORAGE_ACCOUNT_NAME", "sawindfarm")
# Items inside the demo's own workspace keep the names of the guides: the notebooks and the app find them by name,
# and inside a workspace that holds nothing else no name can be taken.
FIXED = {"EVENTHOUSE_NAME": "WindFarmEH", "EVENTSTREAM_NAME": "es-windfarm-edge", "FABRIC_LAKEHOUSE_NAME": "WindFarmLH",
         "COMMAND_EVENTSTREAM_NAME": "WindFarmCommands", "APP_NAME": "WindFarmTwin"}
ASSIGNMENT = re.compile(r'^(?P<key>[A-Z][A-Z0-9_]*)=(?P<quote>"?)(?P<value>[^"\n]*?)(?P=quote)(?P<rest>\s*(#.*)?)$')


def new_suffix(choice=secrets.choice) -> str:
    return "".join(choice(ALPHABET) for _ in range(3))


def valid_suffix(suffix: str) -> bool:
    return len(suffix) == 3 and all(char in ALPHABET for char in suffix)


def generated(suffix: str) -> dict:
    names = {key: f"{base}-{suffix}" for key, base in SUFFIXED.items()}
    names[STORAGE[0]] = f"{STORAGE[1]}{suffix}"
    names["DEPLOYMENT_SUFFIX"] = suffix
    return names


def read_env(path: Path) -> dict:
    """The assignments of a settings file, read as text. The file is not run."""
    values = {}
    for row in Path(path).read_text(encoding="utf-8").splitlines():
        match = ASSIGNMENT.match(row.strip())
        if match:
            values[match["key"]] = match["value"]
    return values


def write_env(path: Path, changes: dict, template: Path | None = None) -> None:
    """Sets the given values in the settings file and leaves every other line as it is.

    A key the file does not have yet is added at the end. Values are written in double quotes; a value with a
    quote, a dollar sign or a backtick in it is refused, because the scripts read this file with the shell.
    """
    for key, value in changes.items():
        if re.search(r'["$`\\\n]', str(value)):
            raise ValueError(f"{key} would hold a character the shell acts on. Refused.")
    source = Path(path) if Path(path).exists() else Path(template)
    left = dict(changes)
    rows = []
    for row in source.read_text(encoding="utf-8").splitlines():
        match = ASSIGNMENT.match(row.strip())
        if match and match["key"] in left:
            rows.append(f'{match["key"]}="{left.pop(match["key"])}"{match["rest"]}')
        else:
            rows.append(row)
    if left:
        rows.append("")
        rows.append("# Written by tools/deploy.py")
        rows.extend(f'{key}="{value}"' for key, value in left.items())
    temporary = Path(str(path) + ".tmp")
    temporary.write_text("\n".join(rows) + "\n", encoding="utf-8")
    temporary.replace(path)
