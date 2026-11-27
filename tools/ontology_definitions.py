#!/usr/bin/env python3
"""Reads the definition of every ontology item of the demo's workspace, as Fabric gives it, and saves it.

Started by infra/10-read-ontology.sh, which gets a token for the signed-in user from the Azure CLI and
hands it over in the environment variable FABRIC_TOKEN. The token is never printed and is sent to the
Fabric API only. Nothing is changed in Fabric: one list of the workspace's items, and one request for
the definition of each ontology.

Why it exists. Notebook 11 writes the old ontology experience, which Microsoft retires on 31 January 2027.
The new experience has a definition of its own, in TMDL. Microsoft's reference for it shows tables bound
to a lakehouse only, and a public report (microsoft/skills-for-fabric, issue 107, open on 27 November 2026)
says that an ontology created from that reference could not be used until annotations were added to its
partitions that the reference does not name. So the definition this repository is to send is written from
what a tenant's own portal wrote, and this tool reads that: make a copy of WindFarmOntology in the new
experience with the button in its banner, run the script, and send the archive it names.

What this rests on (Microsoft Learn, read on 27 November 2026):
  Items - List Items: GET workspaces/{id}/items, each with its type.
  Items - Get Ontology Definition: POST workspaces/{id}/ontologies/{id}/getDefinition, long running, for
      a person and for a service principal; a preview. Its optional parameter `format` has no values
      written down, so none is sent. The answer holds parts with a path and a payload in base64.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from operations_agent import DEFAULT_API, Fabric, FabricError, find_by_name  # noqa: E402
from deployer.core import Redactor  # noqa: E402

OLD, NEW, UNKNOWN = "old experience (JSON)", "new experience (TMDL)", "a form this tool does not know"


def experience(paths) -> str:
    """Which ontology experience a definition is of, told from the names of its parts."""
    paths = [p for p in paths if p != ".platform"]
    if any(p.endswith(".tmdl") for p in paths):
        return NEW
    if any(p == "definition.json" or p.startswith(("EntityTypes/", "RelationshipTypes/")) for p in paths):
        return OLD
    return UNKNOWN


def place(folder: Path, part_path: str) -> Path:
    """Where a part is written. A path that would leave the folder is refused: the name comes from a service."""
    if not part_path or part_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", part_path) or "\x00" in part_path:
        raise FabricError(f"A part of the definition has a name that is no relative path: {part_path!r}.")
    target = (folder / part_path).resolve()
    if folder.resolve() not in target.parents:
        raise FabricError(f"A part of the definition is named outside its folder: {part_path!r}.")
    return target


def decode_parts(response: dict, redact) -> tuple[dict, int, list[str]]:
    """({path: bytes}, how many values that looked like a secret were taken out, parts that are no text)."""
    out, removed, binary = {}, 0, []
    for part in ((response or {}).get("definition") or {}).get("parts") or []:
        path = str(part.get("path") or "")
        if part.get("payloadType", "InlineBase64") != "InlineBase64":
            raise FabricError(f"Part {path} has the payload type {part.get('payloadType')}, which this tool cannot read.")
        try:
            raw = base64.b64decode(part.get("payload") or "", validate=False)
        except ValueError:
            raise FabricError(f"Part {path} is not base64.") from None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            binary.append(path)
            out[path] = raw
            continue
        clean = redact(text)
        removed += clean != text
        out[path] = clean.encode("utf-8")
    return out, removed, binary


def _count(paths, prefix: str) -> int:
    return sum(1 for p in paths if p.startswith(prefix))


def notes(parts: dict) -> list[str]:
    """What the parts show at a glance: enough to read a pasted output without the files."""
    paths = sorted(parts)
    kind = experience(paths)
    if kind == OLD:
        def under(prefix: str) -> int:
            return len({p.split("/")[1] for p in paths if p.startswith(prefix) and p.count("/") >= 2})
        bindings = sum("/DataBindings/" in p for p in paths)
        contexts = sum("/Contextualizations/" in p for p in paths)
        return [f"entity types {under('EntityTypes/')}, relationship types {under('RelationshipTypes/')}, "
                f"data bindings {bindings}, contextualizations {contexts}"]
    if kind != NEW:
        return []
    text = {p: parts[p].decode("utf-8", "replace") for p in paths if p.endswith(".tmdl")}
    everything = "\n".join(text.values())
    tables = "\n".join(t for p, t in text.items() if p.startswith("tables/"))

    def values(pattern: str, source: str = everything) -> list[str]:
        return sorted({m.strip().strip("'\"") for m in re.findall(pattern, source, re.M)})

    series = len(re.findall(r"type:\s*timeSeries", everything))
    additional = len(re.findall(r"^\s*additionalBackingTable\s*$", everything, re.M))
    rows = [f"tables {_count(paths, 'tables/')}, entities {_count(paths, 'entities/')}, rules {_count(paths, 'rules/')}, "
            f"metrics {_count(paths, 'metrics/')}; time series properties {series}, additional backing tables {additional}"]
    rows.append("partition modes: " + (", ".join(values(r"^\s*mode:\s*(.+)$", tables)) or "none"))
    rows.append("expressionSource: " + (", ".join(values(r"^\s*expressionSource:\s*(.+)$", tables)) or "none"))
    # Annotation names only, and the one value that says what kind of item a table comes from.
    names = values(r"^\s*annotation\s+([A-Za-z0-9_]+)\s*=", tables)
    rows.append("annotations on tables: " + (", ".join(names) or "none"))
    kinds = values(r"^\s*annotation\s+ONT_ItemKind\s*=\s*(.+)$", tables)
    if kinds:
        rows.append("ONT_ItemKind: " + ", ".join(kinds))
    if re.search(r"(?i)kusto|eventhouse|kql", everything):
        rows.append("an Eventhouse or KQL source is named in: " + ", ".join(p for p, t in text.items() if re.search(r"(?i)kusto|eventhouse|kql", t)))
    else:
        rows.append("no part names an Eventhouse or a KQL database")
    return rows


def _folder_name(name: str, item_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") + "-" + item_id[:8]


def read_all(fabric: Fabric, env: dict, out, redact=None, now=None) -> int:
    redact = redact or Redactor()
    workspace_name = env.get("FABRIC_WORKSPACE_NAME") or "WindFarmDigitalTwin"
    save_dir = Path(env.get("ONTOLOGY_SAVE_DIR") or ROOT / "fabric" / "ontology" / "saved")
    workspace_id = find_by_name(fabric.listing("workspaces"), workspace_name, "workspace")
    found = [i for i in fabric.listing(f"workspaces/{workspace_id}/items") if i.get("type") == "Ontology"]
    if not found:
        print(f"Workspace {workspace_name} holds no ontology item. Nothing was read.", file=out)
        return 1
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    folder = save_dir / stamp
    index = {"workspace": {"name": workspace_name, "id": workspace_id}, "readAt": stamp, "ontologies": []}
    failed = 0
    for entry in sorted(found, key=lambda e: str(e.get("displayName"))):
        name, item_id = str(entry.get("displayName")), str(entry.get("id"))
        record = {"displayName": name, "id": item_id, "description": entry.get("description") or ""}
        index["ontologies"].append(record)
        print(f"\nOntology {name} ({item_id})", file=out)
        try:
            response = fabric.long_running("POST", f"workspaces/{workspace_id}/ontologies/{item_id}/getDefinition")
            parts, removed, binary = decode_parts(response, redact)
            if not parts:
                raise FabricError("Fabric gave a definition without parts.")
            target = folder / _folder_name(name, item_id)
            files = {path: place(target, path) for path in parts}       # every name looked at before anything is written
            for path, file in files.items():
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(parts[path])
        except FabricError as error:
            failed += 1
            record["error"] = redact(str(error))
            print(f"  Its definition could not be read: {record['error']}", file=out)
            continue
        record.update(experience=experience(parts), folder=target.name,
                      parts=[{"path": path, "bytes": len(parts[path])} for path in sorted(parts)])
        print(f"  {record['experience']}: {len(parts)} parts, {sum(len(d) for d in parts.values())} bytes", file=out)
        for row in notes(parts):
            print(f"  {row}", file=out)
        if removed:
            print(f"  {removed} part(s) held text that looked like a key or a token; it was taken out before saving.", file=out)
        if binary:
            print(f"  not text, saved as they came: {', '.join(binary)}", file=out)
    if failed == len(found):
        print("\nNo definition could be read, so nothing was saved.", file=out)
        return 3
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    archive = save_dir / f"ontology-definitions-{stamp}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(p for p in folder.rglob("*") if p.is_file()):
            bundle.write(file, Path(stamp) / file.relative_to(folder))
    kinds = {r.get("experience") for r in index["ontologies"]}
    print(f"\nSaved: {_shown(folder)}/", file=out)
    print(f"One file to send: {_shown(archive)}", file=out)
    print("It holds the names, the IDs and the SQL endpoint's address of this workspace, and no token or key.", file=out)
    if NEW not in kinds:
        print("None of these is of the new experience. To get one: open the ontology in the workspace, and in the banner "
              "about the new experience select the button that creates a copy. Then run this script again.", file=out)
    print("Nothing was changed in Fabric.", file=out)
    return 3 if failed else 0


def _shown(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv, env=None, out=sys.stdout) -> int:
    env = os.environ if env is None else env
    if argv:
        print("This tool takes no argument.", file=sys.stderr)
        return 2
    redact = Redactor()
    redact.learn(env.get("FABRIC_TOKEN"))
    try:
        fabric = Fabric(env.get("FABRIC_TOKEN", ""), env.get("FABRIC_API") or DEFAULT_API,
                        poll_seconds=float(env.get("FABRIC_POLL_SECONDS") or 3))
        return read_all(fabric, env, out, redact)
    except FabricError as error:
        print(f"ERROR: {redact(str(error))}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
