#!/usr/bin/env python3
"""Upload the site's reference data and documents from the edge to OneLake.

Telemetry travels through MQTT and the eventstream. Files do not: GIS layers,
asset master data, maintenance history and SOP documents are copied from the
edge server's document share (this repository's data/ folder) to the Files
area of the Lakehouse, where notebooks and agents can use them.

    data/reference/**  ->  Files/reference/**
    data/sop/**        ->  Files/sop/**

Only new or changed files are uploaded (compared by size and checksum, or by
modification time when OneLake holds no checksum). Authentication
uses DefaultAzureCredential: the VM's managed identity on the edge VM, or your
own `az login` session on a workstation. The identity needs the Contributor
role on the Fabric workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import ContentSettings, DataLakeServiceClient

ONELAKE_URL = "https://onelake.dfs.fabric.microsoft.com"
SOURCES = (("data/reference", "reference"), ("data/sop", "sop"))
CONTENT_TYPES = {".json": "application/json", ".geojson": "application/geo+json",
                 ".csv": "text/csv", ".md": "text/markdown"}


def md5(path: Path) -> bytes:
    digest = hashlib.md5()  # noqa: S324 - content checksum, not security
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.digest()


def main() -> int:
    p = argparse.ArgumentParser(description="Sync reference data and SOP documents to OneLake.")
    p.add_argument("--workspace", required=True, help="Fabric workspace name or ID")
    p.add_argument("--lakehouse", required=True, help="Lakehouse name (without .Lakehouse) or ID")
    p.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    p.add_argument("--dry-run", action="store_true", help="list what would be uploaded")
    args = p.parse_args()

    root = Path(args.repo_root)
    # A GUID is used as is; a name needs the item type suffix.
    is_guid = len(args.lakehouse) == 36 and args.lakehouse.count("-") == 4
    lakehouse_path = args.lakehouse if is_guid else f"{args.lakehouse}.Lakehouse"

    service = DataLakeServiceClient(ONELAKE_URL, credential=DefaultAzureCredential())
    filesystem = service.get_file_system_client(args.workspace)

    uploaded = skipped = 0
    for local_dir, remote_dir in SOURCES:
        base = root / local_dir
        if not base.is_dir():
            print(f"skip: {base} does not exist", file=sys.stderr)
            continue
        for path in sorted(q for q in base.rglob("*") if q.is_file()):
            remote = f"{lakehouse_path}/Files/{remote_dir}/{path.relative_to(base).as_posix()}"
            client = filesystem.get_file_client(remote)
            checksum = md5(path)
            try:
                props = client.get_file_properties()
                remote_md5 = props.content_settings.content_md5
                if props.size != path.stat().st_size:
                    same = False
                elif remote_md5:
                    same = bytes(remote_md5) == checksum
                else:
                    # No checksum stored: fall back to "remote copy is newer than the local file".
                    same = props.last_modified.timestamp() >= path.stat().st_mtime
            except ResourceNotFoundError:
                same = False
            if same:
                skipped += 1
                continue
            print(f"upload {path.relative_to(root)} -> Files/{remote_dir}/{path.relative_to(base).as_posix()}")
            if not args.dry_run:
                settings = ContentSettings(content_type=CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
                                           content_md5=bytearray(checksum))
                with path.open("rb") as data:
                    client.upload_data(data, overwrite=True, content_settings=settings)
            uploaded += 1

    verb = "would upload" if args.dry_run else "uploaded"
    print(f"{verb} {uploaded} file(s), {skipped} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
