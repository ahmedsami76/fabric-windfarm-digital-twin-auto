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
      written down, so none is sent. The answer holds parts with a path and a payload in base64, and may
      name a format, which is kept: the article on the new definition says only that it "supports the TMDL
      format", and a request that creates an ontology has to name what Fabric names.
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


def definition_of(response) -> dict:
    """The definition in an answer of Get Ontology Definition. An answer of another shape is said as that, not read around."""
    definition = response.get("definition") if isinstance(response, dict) else None
    if isinstance(definition, dict):
        return definition
    if isinstance(response, dict):
        sent = "an object with " + (", ".join(sorted(str(key) for key in response))[:200] or "no member")
    else:
        sent = "nothing" if response is None else f"a {type(response).__name__}"
    raise FabricError(f"Fabric answered without a definition; it sent {sent}.")


def clean(value, redact):
    """What Fabric lists about an item, with anything that looks like a key or a token taken out, whatever its shape."""
    text = redact(json.dumps(value, sort_keys=True, default=str))
    try:
        return json.loads(text)
    except ValueError:
        return text


def decode_parts(definition: dict, redact) -> tuple[dict, int, list[str]]:
    """({path: bytes}, how many values that looked like a secret were taken out, parts that are no text)."""
    out, removed, binary = {}, 0, []
    listed = definition.get("parts") or []
    if not isinstance(listed, list) or not all(isinstance(part, dict) for part in listed):
        raise FabricError("The parts of the definition are not a list of objects.")
    for part in listed:
        path = str(part.get("path") or "")
        if path in out:
            raise FabricError(f"Two parts of the definition are named {path!r}.")       # the second would replace the first
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


def references(parts: dict, items: list) -> list[dict]:
    """The items of the workspace whose ID stands in a part. It says what an ID in a definition points at (the Lakehouse or
    its SQL endpoint, say) from the list this tool has read anyway, so no further call is made for it."""
    text = "\n".join(data.decode("utf-8", "replace") for data in parts.values()).lower()
    found = [{"type": str(i.get("type")), "displayName": str(i.get("displayName")), "id": str(i.get("id"))}
             for i in items if isinstance(i, dict) and i.get("id") and str(i["id"]).lower() in text]
    return sorted(found, key=lambda r: (r["type"], r["displayName"], r["id"]))


def census(items: list) -> dict:
    """How many items of each type the workspace holds: types only, to see an ontology that is listed under another one."""
    count: dict = {}
    for item in items:
        kind = str(item.get("type")) if isinstance(item, dict) else "?"
        count[kind] = count.get(kind, 0) + 1
    return dict(sorted(count.items()))


def related(items: list) -> list[str]:
    """Items whose type speaks of an ontology and is not the one this tool reads."""
    return sorted(f"{i.get('displayName')} of type {i.get('type')}" for i in items
                  if isinstance(i, dict) and "ontolog" in str(i.get("type")).lower() and i.get("type") != "Ontology")


def _folder_name(name: str, item_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") + "-" + item_id[:8]


def read_all(fabric: Fabric, env: dict, out, redact=None, now=None) -> int:
    redact = redact or Redactor()
    workspace_name = env.get("FABRIC_WORKSPACE_NAME") or "WindFarmDigitalTwin"
    save_dir = Path(env.get("ONTOLOGY_SAVE_DIR") or ROOT / "fabric" / "ontology" / "saved")
    workspace_id = find_by_name(fabric.listing("workspaces"), workspace_name, "workspace")
    items = fabric.listing(f"workspaces/{workspace_id}/items")
    found = [i for i in items if i.get("type") == "Ontology"]
    others = related(items)
    if not found:
        print(f"Workspace {workspace_name} holds no ontology item. Nothing was read.", file=out)
        for row in others:
            print(f"It holds {redact(row)}, which this tool does not read: say so, and it can be looked at.", file=out)
        print("Item types there: " + (", ".join(f"{kind} {n}" for kind, n in census(items).items()) or "none"), file=out)
        return 1
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    folder = save_dir / stamp
    index = {"workspace": {"name": workspace_name, "id": workspace_id}, "readAt": stamp, "itemTypes": census(items),
             "notRead": [redact(row) for row in others], "ontologies": []}
    failed = 0
    for entry in sorted(found, key=lambda e: str(e.get("displayName"))):
        name, item_id = str(entry.get("displayName")), str(entry.get("id"))
        # `listing` is everything the list of items says about this one: if Fabric tells the two experiences apart there, it shows.
        record = {"displayName": name, "id": item_id, "description": redact(str(entry.get("description") or "")),
                  "listing": clean(entry, redact)}
        index["ontologies"].append(record)
        print(f"\nOntology {name} ({item_id})", file=out)
        try:
            response = fabric.long_running("POST", f"workspaces/{workspace_id}/ontologies/{item_id}/getDefinition")
            # The reference gives a definition a `format` and names no value for it, and its sample answer has none.
            # Whatever Fabric names here is what a request that creates such an ontology has to name too.
            definition = definition_of(response)
            named = definition.get("format")
            record["format"] = redact(str(named)) if named else None
            record["definitionKeys"] = sorted(str(key) for key in definition)
            parts, removed, binary = decode_parts(definition, redact)
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
        record.update(experience=experience(parts), folder=target.name, references=references(parts, items),
                      workspaceIdInParts=workspace_id.lower() in b"\n".join(parts.values()).decode("utf-8", "replace").lower(),
                      parts=[{"path": path, "bytes": len(parts[path])} for path in sorted(parts)])
        print(f"  {record['experience']}: {len(parts)} parts, {sum(len(d) for d in parts.values())} bytes", file=out)
        print(f"  format, as Fabric names it: {record['format']}" if record["format"] else "  Fabric named no format with this definition", file=out)
        for row in notes(parts):
            print(f"  {row}", file=out)
        named_items = ", ".join(f"{r['displayName']} ({r['type']})" for r in record["references"])
        print("  items of this workspace whose ID is in the parts: " + (named_items or "none"), file=out)
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
    for row in others:
        print(f"\nAlso in the workspace, and not read by this tool: {redact(row)}", file=out)
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
