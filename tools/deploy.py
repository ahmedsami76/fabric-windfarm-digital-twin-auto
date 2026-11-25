#!/usr/bin/env python3
"""The deployment runner of the wind farm demo.

    python3 tools/deploy.py preflight            what is missing before a deployment can run
    python3 tools/deploy.py plan                 every step, what is there already, what would change
    python3 tools/deploy.py apply --approve ID   carry the plan out; run it again to resume
    python3 tools/deploy.py status               the checkpoint, and how fresh the data is now

Only apply changes anything in Azure or Fabric. docs/15-deployment-runner.md says what is automated,
what stays with a person, and what has been proven where.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deployer.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
