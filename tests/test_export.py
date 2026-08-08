import json
import re


def test_export_page_loads(logged_in_client):
    resp = logged_in_client.get("/export")
    assert resp.status_code == 200
    assert "Export" in resp.text


def test_export_json_contains_created_person(logged_in_client):
    logged_in_client.post("/people/new", data={"name": "Exportable Person", "notes": "some notes"})

    resp = logged_in_client.get("/export/json")
    assert resp.status_code == 200
    data = json.loads(resp.text)
    names = [p["name"] for p in data["exported_people"]]
    assert "Exportable Person" in names


def test_export_csv_contains_created_person(logged_in_client):
    logged_in_client.post("/people/new", data={"name": "CSV Person"})

    resp = logged_in_client.get("/export/csv")
    assert resp.status_code == 200
    assert "CSV Person" in resp.text
    assert re.search(r"^name,", resp.text.splitlines()[0])
