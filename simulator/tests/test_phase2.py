"""Phase 2: the model definition must be consistent with itself, with the notebooks and with the report.

What these tests cannot do is run DAX: that needs the semantic model in Fabric. Notebook 07 does it there.
"""
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import model_spec as spec  # noqa: E402

MEASURE_NAMES = {m[0] for m in spec.MEASURES}
COLUMN = re.compile(r"'([^']+)'\[([^\]]+)\]")
BARE = re.compile(r"(?<!')\[([^\]]+)\]")


def check_dax(text: str, where: str) -> None:
    for table, column in COLUMN.findall(text):
        assert table in spec.TABLES, f"{where}: unknown table '{table}'"
        assert column in spec.TABLES[table][1], f"{where}: '{table}' has no column [{column}]"
    for name in BARE.findall(COLUMN.sub("", text)):
        assert name in MEASURE_NAMES, f"{where}: unknown measure [{name}]"
    assert text.count("(") == text.count(")"), f"{where}: unbalanced parentheses"
    assert text.count('"') % 2 == 0, f"{where}: unbalanced quotes"


def test_generated_files_are_current():
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "build-phase2.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_measures_reference_existing_tables_columns_and_measures():
    assert len(MEASURE_NAMES) == len(spec.MEASURES), "a measure name is used twice"
    for name, folder, fmt, dax, text in spec.MEASURES:
        assert folder and fmt and text
        check_dax(dax, name)
    for name in MEASURE_NAMES:                      # a measure may not have the name of a column of its table
        assert name not in spec.TABLES["KPIs"][1]


def test_relationships_and_column_settings_exist():
    for many, column, one, key, _ in spec.RELATIONSHIPS:
        assert column in spec.TABLES[many][1] and key in spec.TABLES[one][1]
    active = [(many, one) for many, _, one, _, on in spec.RELATIONSHIPS if on]
    assert len(active) == len(set(active)), "two active relationships between the same tables"
    for table, column in spec.HIDDEN:
        assert column in spec.TABLES[table][1]
    for table, column, by in spec.SORT_BY:
        assert {column, by} <= set(spec.TABLES[table][1])
    lake = [t for t, _ in spec.TABLES.values()]
    assert len(lake) == len(set(lake))


def test_acceptance_checks_are_well_formed():
    day = dt.date(2026, 11, 20)
    dates = {k: day for k in ("end", "d90", "month", "year", "m6", "m12", "y12")}
    checks = spec.acceptance_checks(dates)
    assert len(checks) >= 10
    lake_tables = {t for t, _ in spec.TABLES.values()}
    for check in checks:
        check_dax(check["dax"], check["id"])
        used = set(re.findall(r"(?:FROM|JOIN)\s+([a-z_0-9]+)", check["sql"]))
        assert used and used <= lake_tables, f"{check['id']}: SQL reads {used - lake_tables}"
        named = set(re.findall(r'"([A-Za-z0-9]+)",', check["dax"]))
        aliases = set(re.findall(r"AS ([A-Za-z0-9]+)", check["sql"]))
        assert named <= aliases, f"{check['id']}: DAX columns {named - aliases} have no SQL column of the same name"
        for key in check["keys"]:
            assert key in check["sql"] and f"[{key}]" in check["dax"]


def test_report_uses_only_fields_of_the_model():
    notebook = json.loads((ROOT / "fabric" / "notebooks" / "08_build_report.ipynb").read_text(encoding="utf-8"))
    builder = next("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code" and "REPORT_JSON" in "".join(c["source"]))
    scope: dict = {}
    exec(builder, scope)
    report = scope["REPORT_JSON"]
    json.loads(report["config"])
    assert len(report["sections"]) == 3
    seen = 0
    for section in report["sections"]:
        for container in section["visualContainers"]:
            config = json.loads(container["config"])
            single = config["singleVisual"]
            assert container["x"] + container["width"] <= section["width"] and container["y"] + container["height"] <= section["height"]
            sources = {f["Name"]: f["Entity"] for f in single["prototypeQuery"]["From"]}
            selected = set()
            for select in single["prototypeQuery"]["Select"]:
                kind = "Measure" if "Measure" in select else "Column"
                table = sources[select[kind]["Expression"]["SourceRef"]["Source"]]
                name = select[kind]["Property"]
                assert select["Name"] == f"{table}.{name}"
                if kind == "Measure":
                    assert table == "KPIs" and name in MEASURE_NAMES, f"report uses unknown measure {name}"
                else:
                    assert name in spec.TABLES[table][1], f"report uses unknown column {table}[{name}]"
                selected.add(select["Name"])
            projected = {p["queryRef"] for group in single["projections"].values() for p in group}
            assert projected == selected
            seen += 1
    assert seen >= 15


def test_table_notebook_writes_every_table_of_the_model():
    notebook = (ROOT / "fabric" / "notebooks" / "05_build_model_tables.ipynb").read_text(encoding="utf-8")
    for table, _ in spec.TABLES.values():
        assert f'\\"{table}\\")' in notebook, f"notebook 05 does not write {table}"


def test_notebooks_that_use_the_library_install_it():
    for path in sorted((ROOT / "fabric" / "notebooks").glob("0[5-8]_*.ipynb")):
        cells = ["".join(c["source"]) for c in json.loads(path.read_text(encoding="utf-8"))["cells"] if c["cell_type"] == "code"]
        uses = [i for i, c in enumerate(cells) if "sempy_labs" in c and not c.startswith("%pip")]
        if uses:                                    # each notebook runs in its own session
            installs = [i for i, c in enumerate(cells) if c.startswith("%pip install") and "semantic-link-labs==" in c]
            assert installs and installs[0] < uses[0], f"{path.name} imports sempy_labs without installing it first"
