"""The deployments of one folder.

Nothing is prepared before a run: there is no settings file to fill in. When a deployment is started, the runner
picks three random characters, makes every name from them, and keeps the settings of that deployment beside its
checkpoint:

    .deploy/<suffix>/demo.env      the settings: generated names, and what was chosen and looked up since
    .deploy/<suffix>/state.json    the checkpoint
    .deploy/current                the suffix of the deployment that commands work on

So one folder can hold many deployments, one after the other or side by side, in one tenant or in several. A new one
is started with `plan --new`; `--deployment SUFFIX` goes back to an earlier one. The scripts the runner starts are
handed the settings file by name (ENV_FILE); a script started by hand finds it through .deploy/current.

config/demo.env belongs to a deployment made by hand, from the guides. The runner does not use it.
"""
from __future__ import annotations

from pathlib import Path

from . import names
from .core import Redactor, Refused, State

# What a person has settled once and would settle the same way again: taken over into the next deployment in the
# same subscription. Names are never taken over.
PREFERENCES = ("LOCATION", "VM_SIZE", "VM_AUTO_SHUTDOWN_UTC", "CUSTOM_LOCATIONS_OID")


def home(root: Path) -> Path:
    return Path(root) / ".deploy"


def env_of(root: Path, suffix: str) -> Path:
    return home(root) / suffix / "demo.env"


def label(root: Path, suffix: str) -> str:
    return f".deploy/{suffix}/demo.env"


def listed(root: Path) -> list[str]:
    """The suffixes of the deployments this folder holds, oldest first."""
    folders = [entry for entry in home(root).glob("*") if entry.is_dir() and names.valid_suffix(entry.name)
               and (entry / "demo.env").is_file()]
    return [entry.name for entry in sorted(folders, key=lambda entry: (entry / "demo.env").stat().st_mtime)]


def current(root: Path) -> str:
    pointer = home(root) / "current"
    suffix = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
    return suffix if suffix in listed(root) else ""


def set_current(root: Path, suffix: str) -> None:
    home(root).mkdir(parents=True, exist_ok=True)
    temporary = home(root) / "current.tmp"
    temporary.write_text(suffix + "\n", encoding="utf-8")
    temporary.replace(home(root) / "current")


def made(root: Path, suffix: str) -> dict:
    """What the checkpoint of a deployment says it has made: the target, with the IDs of group and workspace."""
    return State(home(root) / suffix, Redactor()).data["target"]


def describe(root: Path, suffix: str) -> str:
    settings, target = names.read_env(env_of(root, suffix)), made(root, suffix)
    steps = State(home(root) / suffix, Redactor()).data["steps"]
    complete = sum(1 for step in steps.values() if step.get("status") == "complete")
    what = (f"resource group {settings.get('RESOURCE_GROUP')} made, {complete} steps complete" if target.get("resource_group_id")
            else "nothing made yet")
    return f"{suffix}: subscription {settings.get('SUBSCRIPTION_ID') or 'not set'}; {what}"


def head(env_file: Path, suffix: str) -> None:
    """The template opens with how to copy it for a deployment by hand. A deployment's own file says what it is."""
    rows = env_file.read_text(encoding="utf-8").splitlines()
    first = next((number for number, row in enumerate(rows) if not row.startswith("#")), len(rows))
    rows[:first] = [f"# The settings of deployment {suffix}, kept by tools/deploy.py since the deployment was started.",
                    "# The runner keeps them up to date and hands this file to every script it starts (ENV_FILE). The generated",
                    "# names, the ones that end in the suffix, are not edited by hand. docs/15-deployment-runner.md, Deployments."]
    temporary = Path(str(env_file) + ".tmp")
    temporary.write_text("\n".join(rows) + "\n", encoding="utf-8")
    temporary.replace(env_file)


def adopt_old_settings(root: Path, say) -> None:
    """Up to the fourth issue the runner kept the settings of its one deployment in config/demo.env. Such a file is
    moved to its place beside the checkpoint, once. A file made by hand stays where it is and is not the runner's."""
    old = Path(root) / "config" / "demo.env"
    if not old.is_file():
        return
    settings = names.read_env(old)
    suffix = settings.get("DEPLOYMENT_SUFFIX", "")
    if not names.valid_suffix(suffix):
        return
    if env_of(root, suffix).exists():
        return
    env_of(root, suffix).parent.mkdir(parents=True, exist_ok=True)
    old.replace(env_of(root, suffix))
    head(env_of(root, suffix), suffix)
    set_current(root, suffix)
    say(f"Moved config/demo.env to {label(root, suffix)}: the settings of a deployment are now kept beside its checkpoint, and "
        "config/ holds no settings of the runner.")


def start(root: Path, account: dict, say, like: str = "") -> str:
    """A new deployment: a suffix chosen now, the names made from it, its settings written. Changes nothing in Azure or Fabric."""
    taken = {entry.name for entry in home(root).glob("*")}
    suffix = names.new_suffix()
    while suffix in taken:
        suffix = names.new_suffix()
    values = {**names.generated(suffix), "SUBSCRIPTION_ID": account["id"], "FABRIC_CAPACITY_ID": ""}
    carried = []
    if like:
        before = names.read_env(env_of(root, like))
        if before.get("SUBSCRIPTION_ID") == account["id"]:
            carried = [key for key in PREFERENCES if before.get(key)]
            values.update({key: before[key] for key in carried})
    env_of(root, suffix).parent.mkdir(parents=True, exist_ok=True)
    names.write_env(env_of(root, suffix), values, template=Path(root) / "config" / "demo.env.example")
    head(env_of(root, suffix), suffix)
    set_current(root, suffix)
    say(f"New deployment {suffix}: every name ends in -{suffix}, for subscription {account.get('name')}. Its settings are in "
        f"{label(root, suffix)}. Nothing was changed in Azure or Fabric."
        + (f" Taken over from deployment {like}: {', '.join(carried)}." if carried else ""))
    return suffix


def choose(args, root: Path, az, say, ask) -> str:
    """The deployment this command works on. Starts one when the folder has none, or when asked to."""
    root = Path(root)
    adopt_old_settings(root, say)
    have, now = listed(root), current(root)
    reading_only = args.mode in ("apply", "status")
    if args.new and args.deployment:
        raise Refused("--new starts a deployment and --deployment names one that exists. Give one of them.")
    if args.new:
        if reading_only:
            raise Refused("--new goes with preflight or plan: a deployment starts with a plan.")
        return start(root, az.json("account", "show"), say, like=now)
    if args.deployment:
        if args.deployment not in have:
            raise Refused(f"This folder has no deployment {args.deployment}. "
                          + ("It has: " + "; ".join(describe(root, entry) for entry in have) if have else "It has none yet."))
        set_current(root, args.deployment)
        return args.deployment
    if not now and len(have) == 1:
        now = have[0]
        set_current(root, now)
    if not now:
        if have:
            raise Refused("This folder holds several deployments and none is the current one. Name one with --deployment: "
                          + "; ".join(describe(root, entry) for entry in have))
        if reading_only:
            raise Refused("This folder has no deployment yet. Run plan first: it starts one, with names of its own.")
        return start(root, az.json("account", "show"), say)
    if reading_only:
        return now
    # Two reasons to start another deployment instead of going on with this one. Asked in a terminal; otherwise said.
    account = az.json("account", "show")
    settings = names.read_env(env_of(root, now))
    elsewhere = settings.get("SUBSCRIPTION_ID") and settings["SUBSCRIPTION_ID"] != account.get("id")
    if elsewhere:
        said = (f"Deployment {now} is in subscription {settings['SUBSCRIPTION_ID']}. The Azure CLI is on "
                f"{account.get('name')} ({account.get('id')}).")
        if ask:
            ask.say(said)
            if ask.yes("Start a new deployment here, with names of its own?", default=True):
                return start(root, account, say)
        raise Refused(f"{said} Nothing was changed. Sign in to the subscription of deployment {now}, or start a deployment "
                      "here: python3 tools/deploy.py plan --new")
    group_id = made(root, now).get("resource_group_id")
    if group_id and ask and az.maybe("group", "show", "--name", settings.get("RESOURCE_GROUP", "")) is None:
        ask.say(f"Deployment {now} made the resource group {settings.get('RESOURCE_GROUP')}, and that group no longer exists.")
        if ask.yes("Start a new deployment, with new names?", default=True):
            return start(root, account, say, like=now)
    return now


def check(root: Path, suffix: str) -> dict:
    """The settings of a deployment, read and held to their rule: generated names are not edited by hand."""
    from .steps import NEW_CAPACITY_BASE
    env_file = env_of(root, suffix)
    settings = names.read_env(env_file)
    if settings.get("DEPLOYMENT_SUFFIX") != suffix:
        raise Refused(f"{label(root, suffix)} says DEPLOYMENT_SUFFIX is '{settings.get('DEPLOYMENT_SUFFIX')}', and it is the file "
                      f"of deployment {suffix}. Put the line back.")
    expected = names.generated(suffix)
    if settings.get("FABRIC_WORKSPACE_ID"):
        del expected["FABRIC_WORKSPACE_NAME"]      # an existing workspace you chose: it keeps its name, and is held by its ID
    if settings.get("FABRIC_CAPACITY_NAME"):
        expected["FABRIC_CAPACITY_NAME"] = f"{NEW_CAPACITY_BASE}{suffix}"
    changed = [key for key, value in expected.items() if settings.get(key) != value]
    if changed:
        raise Refused(f"{label(root, suffix)}: {', '.join(changed)} no longer carry the suffix -{suffix}. The names of a "
                      "deployment are not edited by hand. Put them back, or start another deployment: python3 tools/deploy.py "
                      "plan --new")
    return settings


def owner_of_plan(root: Path, digest: str, besides: str) -> str:
    """The deployment whose last plan has this identifier, when it is not the current one."""
    for suffix in listed(root):
        if suffix != besides and State(home(root) / suffix, Redactor()).data.get("last_plan") == digest:
            return suffix
    return ""
