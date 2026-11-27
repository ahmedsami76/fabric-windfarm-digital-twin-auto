"""tools/ontology_definitions.py against a stand-in for the Fabric client.

The stand-in answers the two calls the tool makes, the list of a workspace's items and Get Ontology
Definition, with a definition of the old experience in the shape notebook 11 sends, and one of the new
experience in the shape of Microsoft's reference with the partition annotations a public report describes.
It is not Fabric: what a tenant really returns is what the tool is there to find out.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WS, OLD_ID, NEW_ID = ("11111111-1111-4111-8111-111111111111", "aaaaaaaa-1111-4111-8111-111111111111",
                      "bbbbbbbb-2222-4222-8222-222222222222")
NOW = datetime(2026, 11, 27, 7, 0, 0, tzinfo=timezone.utc)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load("ontology_definitions", ROOT / "tools" / "ontology_definitions.py")

TABLE = """table ref_turbines
	lineageTag: 0d0c3f5e-0000-4000-8000-000000000001

	column turbineId
		dataType: string
		sourceColumn: turbineId

	partition ref_turbines = entity
		mode: directLake
		source
			entityName: ref_turbines
			schemaName: dbo
			expressionSource: 'DirectLake - WindFarmLH'

		annotation ONT_WorkspaceId = 11111111-1111-4111-8111-111111111111
		annotation ONT_ItemKind = Lakehouse
		annotation ONT_ItemName = WindFarmLH
"""
ENTITY = """entity Turbine
	backingTable: ref_turbines
	keyProperty: TurbineId

	property GearboxVibration
		dataType: TimeSeries<double>

		backingConfiguration
			type: timeSeries
			valueColumn: TurbineTelemetry.GearboxVibration
			orderingColumn: TurbineTelemetry.Timestamp

	additionalBackingTable
		table: TurbineTelemetry
		relationship: rel_telemetry_turbine
"""
OLD_PARTS = {".platform": "{}", "definition.json": "{}",
             "EntityTypes/101/definition.json": '{"name": "Turbine"}',
             "EntityTypes/101/DataBindings/b1.json": '{"dataBindingConfiguration": {}}',
             "EntityTypes/102/definition.json": '{"name": "Site"}',
             "RelationshipTypes/201/definition.json": '{"name": "TurbineAtSite"}',
             "RelationshipTypes/201/Contextualizations/c1.json": "{}"}
NEW_PARTS = {".platform": '{"metadata": {"type": "Ontology"}}', "database.tmdl": "database\n\tcompatibilityLevel: 1000000\n",
             "model.tmdl": "model Model\n", "tables/ref_turbines.tmdl": TABLE, "entities/Turbine.tmdl": ENTITY,
             "entities/mynamespace#Site.tmdl": "entity Site\n", "rules/GearboxWatch.tmdl": "rule GearboxWatch\n"}


def definition(parts: dict, named: str | None = None) -> dict:
    out = {"definition": {"parts": [{"path": path, "payload": base64.b64encode(text.encode()).decode(), "payloadType": "InlineBase64"}
                                    for path, text in parts.items()]}}
    if named:
        out["definition"]["format"] = named
    return out


class Pretend:
    """The two calls, and a record of them. Any other call fails the test."""

    def __init__(self, items=None, definitions=None, refuse=()):
        self.items = items if items is not None else [
            {"id": OLD_ID, "displayName": "WindFarmOntology", "type": "Ontology"},
            {"id": NEW_ID, "displayName": "WindFarmOntology (new)", "type": "Ontology"},
            {"id": "c" * 36, "displayName": "WindFarmLH", "type": "Lakehouse"}]
        # The new one names a format and the old one does not: both are possible by the reference, and neither is known.
        self.definitions = definitions or {OLD_ID: definition(OLD_PARTS), NEW_ID: definition(NEW_PARTS, "TMDL")}
        self.refuse, self.calls = set(refuse), []

    def listing(self, path: str) -> list:
        self.calls.append(("GET", path))
        if path == "workspaces":
            return [{"id": WS, "displayName": "WindFarmDigitalTwin-66i"}]
        assert path == f"workspaces/{WS}/items", path
        return self.items

    def long_running(self, method: str, path: str, body=None):
        self.calls.append((method, path))
        assert method == "POST" and body is None and path.endswith("/getDefinition") and "?" not in path, (method, path, body)
        item_id = path.split("/")[-2]
        assert path == f"workspaces/{WS}/ontologies/{item_id}/getDefinition"
        if item_id in self.refuse:
            raise tool.FabricError("The Fabric API answered 400: OperationNotSupportedForItem. It said: not supported", status=400)
        return self.definitions[item_id]


def run(tmp_path, pretend=None, **env):
    out = io.StringIO()
    pretend = pretend or Pretend()
    code = tool.read_all(pretend, {"FABRIC_WORKSPACE_NAME": "WindFarmDigitalTwin-66i", "ONTOLOGY_SAVE_DIR": str(tmp_path), **env}, out, now=NOW)
    return code, out.getvalue(), pretend


def test_both_experiences_are_read_saved_as_they_came_and_packed_into_one_archive(tmp_path):
    code, text, pretend = run(tmp_path)
    assert code == 0, text
    # only reads: one list of workspaces, one of items, one definition for each ontology and for nothing else
    assert pretend.calls == [("GET", "workspaces"), ("GET", f"workspaces/{WS}/items"),
                             ("POST", f"workspaces/{WS}/ontologies/{OLD_ID}/getDefinition"),
                             ("POST", f"workspaces/{WS}/ontologies/{NEW_ID}/getDefinition")]
    folder = tmp_path / "20261127T070000Z"
    assert (folder / "WindFarmOntology-aaaaaaaa" / "EntityTypes" / "101" / "DataBindings" / "b1.json").read_text() == '{"dataBindingConfiguration": {}}'
    assert (folder / "WindFarmOntology_new-bbbbbbbb" / "tables" / "ref_turbines.tmdl").read_text() == TABLE      # tabs and all
    assert (folder / "WindFarmOntology_new-bbbbbbbb" / "entities" / "mynamespace#Site.tmdl").exists()
    index = json.loads((folder / "index.json").read_text())
    assert index["workspace"] == {"name": "WindFarmDigitalTwin-66i", "id": WS}
    assert [(o["displayName"], o["experience"]) for o in index["ontologies"]] == [("WindFarmOntology", tool.OLD), ("WindFarmOntology (new)", tool.NEW)]
    # the format Fabric names with a definition is kept, and its absence is kept as that
    assert [(o["format"], o["definitionKeys"]) for o in index["ontologies"]] == [(None, ["parts"]), ("TMDL", ["format", "parts"])]
    # what the list of items says about each ontology, and what the workspace holds by type: no further call was made for either
    assert index["ontologies"][1]["listing"] == {"id": NEW_ID, "displayName": "WindFarmOntology (new)", "type": "Ontology"}
    assert index["itemTypes"] == {"Lakehouse": 1, "Ontology": 2} and index["notRead"] == []
    archive = tmp_path / "ontology-definitions-20261127T070000Z.zip"
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert "20261127T070000Z/index.json" in names and "20261127T070000Z/WindFarmOntology_new-bbbbbbbb/tables/ref_turbines.tmdl" in names
        assert bundle.read("20261127T070000Z/WindFarmOntology_new-bbbbbbbb/entities/Turbine.tmdl").decode() == ENTITY
        assert len(names) == len(OLD_PARTS) + len(NEW_PARTS) + 1
    assert f"One file to send: {archive}" in text and "Nothing was changed in Fabric." in text


def test_the_output_alone_says_what_each_definition_holds(tmp_path):
    text = run(tmp_path)[1]
    old, new = text.split("Ontology WindFarmOntology (new)")
    assert "old experience (JSON): 7 parts" in old and "Fabric named no format with this definition" in old
    assert "format, as Fabric names it: TMDL" in new and "named no format" not in new
    assert "entity types 2, relationship types 1, data bindings 1, contextualizations 1" in old
    assert "new experience (TMDL): 7 parts" in new
    assert "tables 1, entities 2, rules 1, metrics 0; time series properties 1, additional backing tables 1" in new
    assert "partition modes: directLake" in new and "expressionSource: DirectLake - WindFarmLH" in new
    assert "annotations on tables: ONT_ItemKind, ONT_ItemName, ONT_WorkspaceId" in new and "ONT_ItemKind: Lakehouse" in new
    assert "no part names an Eventhouse or a KQL database" in new
    # a workspace ID is in the files, not on the screen
    assert WS not in text


def test_an_eventhouse_source_is_pointed_out(tmp_path):
    parts = dict(NEW_PARTS, **{"tables/TurbineTelemetry.tmdl": TABLE.replace("ONT_ItemKind = Lakehouse", "ONT_ItemKind = KustoDatabase")})
    pretend = Pretend(definitions={OLD_ID: definition(OLD_PARTS), NEW_ID: definition(parts)})
    text = run(tmp_path, pretend)[1]
    assert "an Eventhouse or KQL source is named in: tables/TurbineTelemetry.tmdl" in text
    assert "ONT_ItemKind: KustoDatabase, Lakehouse" in text


LAKEHOUSE, ENDPOINT, NOTEBOOK = ("cccccccc-3333-4333-8333-333333333333", "dddddddd-4444-4444-8444-444444444444",
                                 "eeeeeeee-5555-4555-8555-555555555555")


def test_an_id_in_a_definition_is_named_as_the_item_of_the_workspace_it_points_at(tmp_path):
    """Whether the portal writes the Lakehouse's ID or its SQL endpoint's into a table's source is what has to be read."""
    parts = dict(NEW_PARTS, **{
        "tables/ref_turbines.tmdl": TABLE + f"\t\tannotation ONT_ItemId = {LAKEHOUSE}\n",
        "expressions.tmdl": f'expression DatabaseQuery = Sql.Database("x.datawarehouse.fabric.microsoft.com", "{ENDPOINT.upper()}")\n'})
    items = [{"id": OLD_ID, "displayName": "WindFarmOntology", "type": "Ontology"},
             {"id": NEW_ID, "displayName": "WindFarmOntology (new)", "type": "Ontology"},
             {"id": LAKEHOUSE, "displayName": "WindFarmLH", "type": "Lakehouse"},
             {"id": ENDPOINT, "displayName": "WindFarmLH", "type": "SQLEndpoint"},
             {"id": NOTEBOOK, "displayName": "11_build_ontology", "type": "Notebook"}]
    pretend = Pretend(items=items, definitions={OLD_ID: definition(OLD_PARTS), NEW_ID: definition(parts)})
    code, text, pretend = run(tmp_path, pretend)
    assert code == 0, text
    assert [path for method, path in pretend.calls if method == "GET"] == ["workspaces", f"workspaces/{WS}/items"]      # no call more
    old, new = text.split("Ontology WindFarmOntology (new)")
    assert "items of this workspace whose ID is in the parts: none" in old
    assert "items of this workspace whose ID is in the parts: WindFarmLH (Lakehouse), WindFarmLH (SQLEndpoint)" in new
    assert LAKEHOUSE not in text and ENDPOINT.upper() not in text and ENDPOINT not in text          # the IDs stay in the files
    index = json.loads((tmp_path / "20261127T070000Z" / "index.json").read_text())
    assert index["ontologies"][0]["references"] == [] and index["ontologies"][0]["workspaceIdInParts"] is False
    assert index["ontologies"][1]["references"] == [{"type": "Lakehouse", "displayName": "WindFarmLH", "id": LAKEHOUSE},
                                                    {"type": "SQLEndpoint", "displayName": "WindFarmLH", "id": ENDPOINT}]
    assert index["ontologies"][1]["workspaceIdInParts"] is True
    assert index["itemTypes"] == {"Lakehouse": 1, "Notebook": 1, "Ontology": 2, "SQLEndpoint": 1}


def test_an_ontology_listed_under_another_type_is_named_and_not_read(tmp_path):
    """Nothing says that the copy of the new experience is listed as `Ontology`. If it is not, the output has to say what is there."""
    copy = {"id": NEW_ID, "displayName": "WindFarmOntology (new)", "type": "OntologyV2"}
    code, text, pretend = run(tmp_path, Pretend(items=[{"id": OLD_ID, "displayName": "WindFarmOntology", "type": "Ontology"}, copy]))
    assert code == 0 and [path for method, path in pretend.calls if method == "POST"] == [f"workspaces/{WS}/ontologies/{OLD_ID}/getDefinition"]
    assert "Also in the workspace, and not read by this tool: WindFarmOntology (new) of type OntologyV2" in text
    index = json.loads((tmp_path / "20261127T070000Z" / "index.json").read_text())
    assert index["notRead"] == ["WindFarmOntology (new) of type OntologyV2"] and index["itemTypes"] == {"Ontology": 1, "OntologyV2": 1}
    # and with nothing of the type this tool reads: no call, nothing saved, and the output alone says what the workspace lists
    other = tmp_path / "other"
    code, text, pretend = run(other, Pretend(items=[copy, {"id": LAKEHOUSE, "displayName": "WindFarmLH", "type": "Lakehouse"}]))
    assert code == 1 and not any(method == "POST" for method, _ in pretend.calls) and not other.exists()
    assert "It holds WindFarmOntology (new) of type OntologyV2, which this tool does not read" in text
    assert "Item types there: Lakehouse 1, OntologyV2 1" in text


@pytest.mark.parametrize("answer, said", [
    (None, "Fabric answered without a definition; it sent nothing."),
    (["parts"], "Fabric answered without a definition; it sent a list."),
    ({"message": "<html>"}, "Fabric answered without a definition; it sent an object with message."),
    ({"definition": {"parts": {"path": "model.tmdl"}}}, "The parts of the definition are not a list of objects."),
    ({"definition": {"parts": ["model.tmdl"]}}, "The parts of the definition are not a list of objects."),
    ({"definition": {"format": "TMDL", "parts": []}}, "Fabric gave a definition without parts."),
])
def test_an_answer_of_another_shape_is_said_as_that_and_ends_nothing_else(tmp_path, answer, said):
    pretend = Pretend(definitions={OLD_ID: definition(OLD_PARTS), NEW_ID: answer})
    code, text, _ = run(tmp_path, pretend)
    assert code == 3 and f"Its definition could not be read: {said}" in text, text
    assert (tmp_path / "20261127T070000Z" / "WindFarmOntology-aaaaaaaa" / "definition.json").exists()        # the other one is saved
    index = json.loads((tmp_path / "20261127T070000Z" / "index.json").read_text())
    assert index["ontologies"][1]["error"] == said and "parts" not in index["ontologies"][1]
    # what Fabric did name is kept beside the error
    assert index["ontologies"][1].get("format") == ("TMDL" if isinstance(answer, dict) and "definition" in answer and "format" in answer["definition"] else None)


def test_two_parts_of_one_name_are_refused_since_the_second_would_replace_the_first(tmp_path):
    twice = definition({"model.tmdl": "model Model\n"})
    twice["definition"]["parts"] += definition({"model.tmdl": "model Other\n"})["definition"]["parts"]
    pretend = Pretend(items=[{"id": NEW_ID, "displayName": "WindFarmOntology (new)", "type": "Ontology"}], definitions={NEW_ID: twice})
    code, text, _ = run(tmp_path / "saved", pretend)
    assert code == 3 and "Two parts of the definition are named 'model.tmdl'." in text
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_what_the_list_says_about_an_ontology_is_kept_without_anything_that_looks_like_a_token(tmp_path):
    token = "eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJodHRwczovL2FwaS5mYWJyaWMifQ.c2lnbmF0dXJlLW9mLXRoZS10ZXN0"
    entry = {"id": NEW_ID, "displayName": "WindFarmOntology (new)", "type": "Ontology", "description": f"copied with {token}",
             "folderId": None, "tags": [{"displayName": "demo"}], "experience": "new"}
    code, text, _ = run(tmp_path, Pretend(items=[entry]))
    saved = (tmp_path / "20261127T070000Z" / "index.json").read_text()
    assert code == 0 and token not in saved and token not in text
    listing = json.loads(saved)["ontologies"][0]["listing"]
    assert listing["experience"] == "new" and listing["tags"] == [{"displayName": "demo"}] and listing["folderId"] is None
    assert sorted(listing) == sorted(entry)


def test_only_the_old_experience_there_says_how_to_get_the_new_one(tmp_path):
    pretend = Pretend(items=[{"id": OLD_ID, "displayName": "WindFarmOntology", "type": "Ontology"}])
    code, text, _ = run(tmp_path, pretend)
    assert code == 0 and "None of these is of the new experience" in text and "select the button that creates a copy" in text


def test_no_ontology_in_the_workspace_reads_and_writes_nothing(tmp_path):
    pretend = Pretend(items=[{"id": "c" * 36, "displayName": "WindFarmLH", "type": "Lakehouse"}])
    code, text, pretend = run(tmp_path, pretend)
    assert code == 1 and "holds no ontology item" in text
    assert not any(method == "POST" for method, _ in pretend.calls) and not list(tmp_path.iterdir())


def test_one_definition_fabric_does_not_give_out_is_named_and_the_other_is_still_saved(tmp_path):
    code, text, _ = run(tmp_path, Pretend(refuse={OLD_ID}))
    assert code == 3
    assert "Its definition could not be read: The Fabric API answered 400: OperationNotSupportedForItem" in text
    assert (tmp_path / "20261127T070000Z" / "WindFarmOntology_new-bbbbbbbb" / "model.tmdl").exists()
    index = json.loads((tmp_path / "20261127T070000Z" / "index.json").read_text())
    assert "error" in index["ontologies"][0] and "parts" in index["ontologies"][1]


def test_when_none_can_be_read_nothing_is_saved(tmp_path):
    code, text, _ = run(tmp_path, Pretend(refuse={OLD_ID, NEW_ID}))
    assert code == 3 and "No definition could be read, so nothing was saved." in text and not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["../outside.tmdl", "/etc/passwd", "tables/../../outside.tmdl", "C:\\temp\\x.tmdl", ""])
def test_a_part_named_outside_its_folder_is_refused_and_not_written(tmp_path, name):
    pretend = Pretend(items=[{"id": NEW_ID, "displayName": "WindFarmOntology (new)", "type": "Ontology"}],
                      definitions={NEW_ID: definition({"model.tmdl": "model Model\n", name: "x"})})
    code, text, _ = run(tmp_path / "saved", pretend)
    assert code == 3 and "could not be read" in text and "nothing was saved" in text
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]          # not the part with the bad name, and not the one before it


def test_text_that_looks_like_a_key_or_a_token_is_taken_out_before_saving(tmp_path):
    token = "eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJodHRwczovL2FwaS5mYWJyaWMifQ.c2lnbmF0dXJlLW9mLXRoZS10ZXN0"
    parts = dict(NEW_PARTS, **{"expressions.tmdl": f'expression DatabaseQuery = Sql.Database("x.datawarehouse.fabric.microsoft.com", "id")\n\t// {token}\n\t// AccountKey=abcdefgh12345678\n'})
    pretend = Pretend(definitions={OLD_ID: definition(OLD_PARTS), NEW_ID: definition(parts)})
    code, text, _ = run(tmp_path, pretend)
    saved = (tmp_path / "20261127T070000Z" / "WindFarmOntology_new-bbbbbbbb" / "expressions.tmdl").read_text()
    assert code == 0 and token not in saved and "abcdefgh12345678" not in saved and "x.datawarehouse.fabric.microsoft.com" in saved
    assert "1 part(s) held text that looked like a key or a token" in text
    with zipfile.ZipFile(tmp_path / "ontology-definitions-20261127T070000Z.zip") as bundle:
        assert all(token.encode() not in bundle.read(n) for n in bundle.namelist())


def test_the_token_is_never_printed_and_an_unreachable_api_is_said_as_that(capsys):
    code = tool.main([], env={"FABRIC_TOKEN": "t0ken-of-the-test-0123456789", "FABRIC_API": "http://127.0.0.1:9/v1"})
    shown = capsys.readouterr()
    assert code == 3 and "Could not reach the Fabric API" in shown.err and "t0ken-of-the-test" not in shown.err + shown.out
    assert tool.main(["--delete"], env={}) == 2


def test_which_experience_a_definition_is_of():
    assert tool.experience([".platform", "definition.json", "EntityTypes/1/definition.json"]) == tool.OLD
    assert tool.experience([".platform", "database.tmdl", "entities/Turbine.tmdl"]) == tool.NEW
    assert tool.experience([".platform"]) == tool.UNKNOWN
