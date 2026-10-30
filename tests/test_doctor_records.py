"""Prepared doctor's portal: source integrity, real local staff actions and print output."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import doctor_records as records
import doctor_records_api
import recovery


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(records, "STORE_PATH", tmp_path / "doctor-prepared.json")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(doctor_records_api.router)
    return TestClient(app)


def test_prepared_report_fields_are_supported_by_patient_turns():
    view = records.workspace()
    report = view["report"]
    records.validate_report_evidence(report)
    assert report["provenance"] == "Prepared case"
    assert report["patient"]["identity_basis"].startswith("Explicit prepared case selection")
    assert report["audio_available"] is False
    assert not records.STORE_PATH.exists()  # Reading preparation never touches saved records.


@pytest.mark.parametrize("fault", ["quote", "role", "duplicate"])
def test_invalid_history_evidence_is_rejected(fault):
    report = deepcopy(records.prepared_case()["report"])
    if fault == "quote":
        report["fields"][0]["evidence"][0]["quote"] = "Words the patient did not say"
    elif fault == "role":
        report["turns"][1]["role"] = "agent"
    else:
        report["turns"].append(deepcopy(report["turns"][1]))
    with pytest.raises(ValueError):
        records.validate_report_evidence(report)


def test_aftercare_uses_existing_rule_engine_and_retains_exact_change(monkeypatch):
    calls = []
    original = recovery.evaluate_rules
    def evaluate(turns, extraction):
        calls.append(turns)
        return original(turns, extraction)
    monkeypatch.setattr(recovery, "evaluate_rules", evaluate)
    view = records.workspace()["aftercare"]
    assert len(calls) == 2
    first, second = view["calls"]
    assert first["decision"]["status"] == "report_saved"
    assert second["decision"]["status"] == "review_requested"
    assert second["decision"]["criterion_ids"] == ["DEMO-CHANGE-01"]
    assert second["decision"]["routine_questions_stopped"] is True
    assert [first["postoperative_day"], second["postoperative_day"]] == [2, 3]
    handover = view["handover"]
    ref = handover["evidence"][0]
    source = next(turn for turn in second["turns"] if turn["id"] == ref["turn_id"])
    assert ref["quote"] in source["text"]
    assert handover["protocol_version"] == recovery.protocol()["version"]
    assert handover["external_delivery"] == "not_attempted"
    assert view["notification"]["channel"] == "doctor_portal"


def test_invalid_recovery_source_remains_unresolved_without_invented_quote(monkeypatch):
    case = records.prepared_case()
    case["calls"][-1]["extraction"]["observations"][0]["evidence"][0]["quote"] = "Invented"
    monkeypatch.setattr(records, "prepared_case", lambda: deepcopy(case))
    handover = records.workspace()["aftercare"]["handover"]
    assert handover["status"] == "review_requested"
    assert handover["evidence"] == []
    assert handover["issues"]
    assert handover["resolution"] == "not_recorded"


def test_missing_recovery_information_requests_review_and_never_claims_audio(monkeypatch):
    case = records.prepared_case()
    case["calls"][-1]["extraction"]["observations"] = []
    monkeypatch.setattr(records, "prepared_case", lambda: deepcopy(case))
    view = records.workspace()["aftercare"]
    assert view["handover"]["status"] == "review_requested"
    assert view["handover"]["issues"]
    assert all(call["audio_available"] is False for call in view["calls"])
    assert all(turn["audio"] is None for call in view["calls"] for turn in call["turns"])


def test_unchanged_report_never_clears_recovery_or_cancels_care(monkeypatch):
    case = records.prepared_case()
    case["calls"] = [case["calls"][0]]
    monkeypatch.setattr(records, "prepared_case", lambda: deepcopy(case))
    view = records.workspace()["aftercare"]
    assert view["handover"] is None
    assert view["clinical_clearance"] is False
    assert view["scheduled_care"] == "unchanged"
    assert view["scheduled_review_date"] == "2026-10-31"
    with pytest.raises(ValueError, match="No review"):
        records.acknowledge("Dr. Review")


def test_staff_acknowledgement_and_disposition_have_actual_audit_and_no_resolution():
    first = records.acknowledge("Dr. Review", expected_revision=0)
    handover = first["aftercare"]["handover"]
    assert handover["status"] == "acknowledged"
    assert handover["acknowledged_at"] and handover["staff"] == "Dr. Review"
    assert handover["resolution"] == "not_recorded"
    assert first["aftercare"]["notification"]["status"] == "acknowledged"
    assert records.workspace()["aftercare"]["handover"] == handover
    final = records.record_disposition("Dr. Review", "Clinician assessment pending.", expected_revision=1)
    assert final["aftercare"]["handover"]["status"] == "disposition_recorded"
    assert final["aftercare"]["handover"]["resolution"] == "not_recorded"
    assert [event["action"] for event in final["aftercare"]["audit"]] == ["acknowledged", "disposition_recorded"]
    assert final["aftercare"]["handover"]["external_delivery"] == "not_attempted"


def test_staff_actions_are_required_and_stale_writes_do_not_overwrite():
    with pytest.raises(ValueError, match="staff name"):
        records.acknowledge(" ")
    with pytest.raises(ValueError, match="Acknowledge"):
        records.record_disposition("Dr. Review", "Pending")
    records.acknowledge("Dr. Review")
    before = records.STORE_PATH.read_bytes()
    with pytest.raises(ValueError, match="changed"):
        records.record_disposition("Dr. Other", "Other note", expected_revision=0)
    assert records.STORE_PATH.read_bytes() == before


def test_room_edits_are_administrative_and_apply_to_printed_report():
    view = records.update_routing("Coordinator", "4012", "East 4013")
    route = view["report"]["routing"]
    assert [step["room"] for step in route["steps"]] == ["4012", "East 4013", None]
    assert route["status"] == "confirmation_pending"
    assert "not a clinical test order" in route["source"]
    assert route["updated_by"] == "Coordinator"
    assert records.workspace()["report"]["routing"] == route
    with pytest.raises(ValueError):
        records.update_routing("Coordinator", "<script>", "4013")


def test_reset_only_changes_owned_prepared_actions_and_preserves_other_records(tmp_path):
    other = tmp_path / "existing-patient.json"
    other.write_text("keep existing record", encoding="utf-8")
    records.acknowledge("Dr. Review")
    records.update_routing("Coordinator", "4012", "4014")
    view = records.reset_prepared()
    assert view["aftercare"]["handover"]["status"] == "review_requested"
    assert view["report"]["routing"]["steps"][0]["room"] == "4011"
    assert other.read_text(encoding="utf-8") == "keep existing record"


def test_reset_refuses_foreign_store():
    records.STORE_PATH.write_text(json.dumps({"owner": "unrelated", "case_id": "patient-record"}))
    before = records.STORE_PATH.read_bytes()
    with pytest.raises(ValueError, match="unrelated"):
        records.reset_prepared()
    assert records.STORE_PATH.read_bytes() == before


def test_pdf_routes_are_real_inline_or_downloadable_documents(client):
    for path in ("/doctor/api/reports/prepared/pdf", "/doctor/api/reports/prepared/visit.pdf"):
        inline = client.get(path)
        assert inline.status_code == 200
        assert inline.content.startswith(b"%PDF-")
        assert inline.headers["content-disposition"].startswith("inline;")
        assert inline.headers["cache-control"] == "no-store"
        download = client.get(path + "?download=true")
        assert download.headers["content-disposition"].startswith("attachment;")
        assert download.content == inline.content


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="PDF text inspection requires poppler")
def test_printed_history_and_visit_include_room_route_and_fixed_source_date(tmp_path):
    for name, content in (("history", records.report_pdf()), ("visit", records.visit_pdf())):
        path = tmp_path / (name + ".pdf")
        path.write_bytes(content)
        text = subprocess.check_output(["pdftotext", str(path), "-"], text=True)
        assert "Room 4011" in text and "Room 4013" in text
        assert "Vision check" in text and "NCT" in text
        assert "Clinician consultation" in text
        assert "26 Oct 2026" in text
        assert "Prepared case" in text
        assert "Confirm tests and rooms" in text
        if name == "history":
            assert "Blurred seeing in the right eye" in text


def test_api_staff_actions_and_validation(client):
    before = client.get("/doctor/api/workspace").json()
    assert before["aftercare"]["handover"]["status"] == "review_requested"
    assert client.post("/doctor/api/aftercare/acknowledge", json={}).status_code == 422
    response = client.post("/doctor/api/aftercare/acknowledge", json={"staff": "Dr. Review", "expected_revision": 0})
    assert response.status_code == 200
    assert response.json()["aftercare"]["handover"]["status"] == "acknowledged"
    stale = client.post("/doctor/api/routing", json={"staff": "Coordinator", "vision_room": "4001", "nct_room": "4002", "expected_revision": 0})
    assert stale.status_code == 409
    reset = client.post("/doctor/api/prepared/reset", json={"expected_revision": 1})
    assert reset.status_code == 200
    assert reset.json()["aftercare"]["handover"]["status"] == "review_requested"
