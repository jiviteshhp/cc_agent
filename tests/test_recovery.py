"""Synthetic recovery safety behavior; no provider credentials or patient records."""
import asyncio
from copy import deepcopy
import json

import pytest

import recovery


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "STORE_PATH", tmp_path / "state" / "recovery-demo.json")


def test_changed_report_triggers_inspectable_protocol_and_exact_evidence():
    state = recovery.replay("worsening")
    assert state["episode"]["postoperative_day"] == 3
    report = state["reports"][-1]
    assert report["decision"]["routine_questions_stopped"]
    assert report["decision"]["criterion_ids"] == ["DEMO-CHANGE-01"]
    assert state["handover"]["protocol_version"] == "0.1.0-demo"
    assert state["handover"]["status"] == "review_requested"
    assert state["protocol"]["approval_status"] == "illustrative_only_not_clinically_approved"
    for obs in report["extraction"]["observations"]:
        for ref in obs["evidence"]:
            turn = next(t for t in report["turns"] if t["id"] == ref["turn_id"])
            assert turn["role"] == "patient"
            assert ref["quote"] in turn["text"]


def test_stable_is_saved_without_clearance_or_cancellation():
    state = recovery.replay("stable")
    assert state["reports"][-1]["decision"]["status"] == "report_saved"
    assert not state["clinical_clearance"]
    assert state["scheduled_care"] == "unchanged"
    assert state["episode"]["discharge"]["scheduled_review_date"] == "2026-10-31"
    assert state["handover"] is None
    assert "not clinical clearance" in state["protocol"]["messages"]["report_saved"]["en"]


@pytest.mark.parametrize("branch", ["missing", "contradictory"])
def test_missing_or_contradictory_is_review_not_normal(branch):
    state = recovery.replay(branch)
    report = state["reports"][-1]
    assert "DEMO-UNCERTAIN-02" in report["decision"]["criterion_ids"]
    assert report["decision"]["issues"]
    assert state["handover"]["status"] == "review_requested"


@pytest.mark.parametrize("bad_ref", [
    {"turn_id": "nonexistent", "quote": "दर्द कल जैसा ही हल्का है।"},
    {"turn_id": "stable-patient-1", "quote": "invented patient quote"},
    {"turn_id": "agent", "quote": "pain is fine"},
])
def test_invalid_transcript_evidence_excluded_and_reviewed(bad_ref):
    fixture = recovery._read_fixture("replays.json")["stable"]
    fixture["turns"].append({"id": "agent", "role": "assistant", "text": "pain is fine"})
    fixture["extraction"]["observations"][0]["evidence"] = [bad_ref]
    state = recovery.process_report(fixture["turns"], fixture["extraction"])
    report = state["reports"][-1]
    assert "DEMO-EVIDENCE-03" in report["decision"]["criterion_ids"]
    assert all(o["symptom"] != "pain" for o in report["extraction"]["observations"])
    assert report["raw_extraction"]["observations"][0]["evidence"] == [bad_ref]


def test_live_turn_cannot_smuggle_recording_or_fixture_audio():
    fixture = recovery._read_fixture("replays.json")["stable"]
    fixture["turns"][0]["audio"] = {"url": "/fake.wav", "start": 0, "end": 20}
    state = recovery.process_report(fixture["turns"], fixture["extraction"],
                                    mode="live_microphone", extraction_source="live_runtime_llm")
    assert state["reports"][-1]["turns"][0]["audio"] is None


def test_acknowledgement_and_disposition_never_mean_clinical_resolution():
    recovery.replay("worsening")
    with pytest.raises(ValueError, match="Acknowledge"):
        recovery.staff_action("disposition", "Demo nurse", "Clinician review planned")
    state = recovery.staff_action("acknowledge", "Demo nurse")
    assert state["handover"]["status"] == "acknowledged"
    assert state["handover"]["acknowledged_at"]
    assert state["handover"]["resolution"] == "not_recorded"
    state = recovery.staff_action("disposition", "Demo nurse", "Clinician review planned; contact pending")
    assert state["handover"]["status"] == "disposition_recorded"
    assert state["handover"]["resolution"] == "not_recorded"
    assert state["handover"]["disposition"]["note"] == "Clinician review planned; contact pending"
    assert [item["action"] for item in state["audit"]][-2:] == ["acknowledge", "disposition"]


def test_failed_transfer_remains_unresolved_even_after_acknowledgement():
    recovery.replay("worsening")
    state = recovery.staff_action("transfer_failed", "Demo nurse")
    assert state["handover"]["transfer_status"] == "failed"
    assert state["handover"]["status"] == "review_requested"
    state = recovery.staff_action("acknowledge", "Demo nurse")
    assert state["handover"]["transfer_status"] == "failed"
    assert state["handover"]["resolution"] == "not_recorded"
    assert state["protocol"]["fallback_instructions"] is None


def test_stable_later_report_cannot_clear_previous_review():
    recovery.replay("worsening")
    state = recovery.replay("stable")
    assert state["reports"][-1]["decision"]["status"] == "report_saved"
    assert state["handover"]["status"] == "review_requested"
    assert len(state["handover"]["report_ids"]) == 1


def test_new_worsening_after_ack_needs_new_review_without_erasing_audit():
    recovery.replay("worsening")
    recovery.staff_action("acknowledge", "Demo nurse")
    recovery.staff_action("disposition", "Demo nurse", "Local clinician review planned")
    state = recovery.replay("worsening")
    assert state["handover"]["status"] == "review_requested"
    assert state["handover"]["acknowledged_at"] is None
    assert any(item["action"] == "disposition" for item in state["audit"])


def test_explicit_correction_preserves_both_statements_and_requests_review():
    turns = [{"id": "p1", "role": "patient", "text": "Pain is worse."},
             {"id": "p2", "role": "patient", "text": "Correction: pain is the same. Seeing is the same."}]
    extraction = {"observations": [
        {"id": "o1", "symptom": "pain", "change": "worse", "description": "Pain worse", "evidence": [{"turn_id": "p1", "quote": "Pain is worse."}]},
        {"id": "o2", "symptom": "pain", "change": "same", "description": "Pain unchanged, explicit correction", "corrects": "o1", "evidence": [{"turn_id": "p2", "quote": "Correction: pain is the same."}]},
        {"id": "o3", "symptom": "vision", "change": "same", "description": "Seeing unchanged", "evidence": [{"turn_id": "p2", "quote": "Seeing is the same."}]},
    ], "uncertainties": []}
    state = recovery.process_report(turns, extraction)
    report = state["reports"][-1]
    assert len(report["turns"]) == 2
    assert report["extraction"]["observations"][0]["superseded_by"] == "o2"
    assert report["decision"]["criterion_ids"] == ["DEMO-UNCERTAIN-02"]


def test_safe_reset_only_synthetic_record_and_rejects_foreign_store(tmp_path):
    sentinel = tmp_path / "real-call.json"
    sentinel.write_text("preserve this existing record")
    recovery.replay("worsening")
    old_revision = recovery.load_state()["revision"]
    state = recovery.reset()
    assert len(state["reports"]) == 1
    assert state["handover"] is None
    assert state["revision"] > old_revision
    assert sentinel.read_text() == "preserve this existing record"
    foreign = {"synthetic_demo": False, "episode": {"id": "unrelated-episode"}}
    recovery.STORE_PATH.write_text(json.dumps(foreign))
    with pytest.raises(ValueError, match="outside the synthetic"):
        recovery.reset()
    assert json.loads(recovery.STORE_PATH.read_text()) == foreign


def test_old_live_result_cannot_repopulate_after_reset():
    revision = recovery.load_state()["revision"]
    recovery.reset()
    with pytest.raises(ValueError, match="Demo changed"):
        recovery.process_report([], {"observations": [], "uncertainties": []}, expected_revision=revision)
    assert len(recovery.load_state()["reports"]) == 1


def test_blank_live_submission_never_calls_provider(monkeypatch):
    async def unexpected(turns):
        raise AssertionError("Blank answer must not call the provider")
    monkeypatch.setattr(recovery, "extract_live", unexpected)
    state = asyncio.run(recovery.submit_live(" "))
    assert state["handover"]["status"] == "review_requested"
    assert state["reports"][-1]["extraction_source"] == "unavailable"


def test_live_provider_failure_never_falls_back_to_success(monkeypatch):
    async def failed(turns):
        raise TimeoutError("provider unavailable")
    monkeypatch.setattr(recovery, "extract_live", failed)
    with pytest.raises(TimeoutError):
        asyncio.run(recovery.submit_live("synthetic statement"))
    assert len(recovery.load_state()["reports"]) == 1


def test_replay_passes_precomputed_extraction_through_real_validator(monkeypatch):
    called = []
    original = recovery.evaluate_rules
    def traced(turns, extraction):
        called.append((turns, extraction))
        return original(turns, extraction)
    monkeypatch.setattr(recovery, "evaluate_rules", traced)
    state = recovery.replay("worsening")
    assert len(called) == 1
    assert state["reports"][-1]["extraction_source"] == "precomputed_synthetic_fixture"


def test_postoperative_day_uses_dates_not_current_clock():
    assert recovery.postoperative_day("2026-10-27", "2026-10-29") == 2
    assert recovery.postoperative_day("2026-10-27", "2026-10-30") == 3
    with pytest.raises(ValueError):
        recovery.postoperative_day("2026-10-27", "2026-10-26")


def test_duplicate_transcript_ids_cannot_be_evidence():
    fixture = recovery._read_fixture("replays.json")["stable"]
    fixture["turns"].append(deepcopy(fixture["turns"][0]))
    state = recovery.process_report(fixture["turns"], fixture["extraction"])
    report = state["reports"][-1]
    assert report["extraction"]["observations"] == []
    assert "DEMO-EVIDENCE-03" in report["decision"]["criterion_ids"]


def test_correction_replay_is_visible_and_protocol_version_is_recorded():
    state = recovery.replay("correction")
    report = state["reports"][-1]
    assert report["protocol_version"] == state["protocol"]["version"]
    assert report["extraction"]["observations"][0]["superseded_by"] == "correction-pain-2"
    assert report["extraction"]["observations"][-1]["corrects"] == "correction-pain-1"


def test_failed_text_extraction_persists_source_for_review(monkeypatch):
    import recovery_api
    async def failed(turns):
        raise TimeoutError("provider unavailable")
    monkeypatch.setattr(recovery, "extract_live", failed)
    response = asyncio.run(recovery_api.report(recovery_api.ReportRequest(text="synthetic patient statement")))
    assert response.status_code == 503
    body = json.loads(response.body)
    assert "no replay" in body["detail"]
    state = body["state"]
    assert state["handover"]["status"] == "review_requested"
    assert state["reports"][-1]["turns"][0]["text"] == "synthetic patient statement"
    assert state["reports"][-1]["extraction_source"] == "unavailable"


@pytest.mark.parametrize("mutation", ["version", "predicate", "missing_rule", "approved", "missing_symptom"])
def test_unsupported_protocol_fails_closed(monkeypatch, mutation):
    original = recovery._read_fixture
    spec = original("protocol.v0.1.0.json")
    if mutation == "version":
        spec["version"] = "99.0-future"
    elif mutation == "predicate":
        spec["rules"][0]["predicate"] = "opaque_llm_risk"
    elif mutation == "missing_rule":
        spec["rules"].pop(0)
    elif mutation == "approved":
        spec["approval_status"] = "approved"
    else:
        spec["required_symptoms"] = ["pain"]
    monkeypatch.setattr(recovery, "_read_fixture", lambda name: spec if name.startswith("protocol") else original(name))
    with pytest.raises(ValueError, match="Unsupported illustrative protocol"):
        recovery.replay("stable")
    assert not recovery.STORE_PATH.exists()


def test_stored_future_protocol_is_rejected_without_mutation():
    state = recovery.replay("worsening")
    state["protocol"]["version"] = "future"
    recovery.STORE_PATH.write_text(json.dumps(state))
    before = recovery.STORE_PATH.read_bytes()
    with pytest.raises(ValueError, match="protocol version is unsupported"):
        recovery.staff_action("acknowledge", "Demo nurse")
    assert recovery.STORE_PATH.read_bytes() == before


def test_malformed_unhashable_evidence_is_reviewed_not_crash():
    fixture = recovery._read_fixture("replays.json")["stable"]
    fixture["extraction"]["observations"][0]["evidence"][0]["turn_id"] = ["invalid"]
    fixture["extraction"]["observations"][1]["symptom"] = {"invalid": True}
    state = recovery.process_report(fixture["turns"], fixture["extraction"])
    assert state["reports"][-1]["extraction"]["observations"] == []
    assert state["handover"]["status"] == "review_requested"


def test_model_prose_cannot_introduce_diagnosis_into_validated_summary():
    fixture = recovery._read_fixture("replays.json")["stable"]
    fixture["extraction"]["observations"][0]["description"] = "You have a complication; change treatment"
    state = recovery.process_report(fixture["turns"], fixture["extraction"])
    report = state["reports"][-1]
    assert report["extraction"]["observations"][0]["description"] == "Patient reports no change in pain"
    assert "change treatment" in report["raw_extraction"]["observations"][0]["description"]


def test_invalid_loaded_chronology_does_not_display_impossible_postoperative_day():
    state = recovery.replay("stable")
    state["reports"][-1]["date"] = "2026-10-26"
    recovery.STORE_PATH.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="precedes"):
        recovery.load_state()


def test_delayed_live_extraction_result_rejected_after_reset(monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(turns):
            entered.set()
            await release.wait()
            return {"observations": [], "uncertainties": ["Incomplete synthetic answer"]}
        monkeypatch.setattr(recovery, "extract_live", delayed)
        task = asyncio.create_task(recovery.submit_live("synthetic statement"))
        await entered.wait()
        recovery.reset()
        release.set()
        with pytest.raises(ValueError, match="Demo changed"):
            await task
    asyncio.run(run())
    assert len(recovery.load_state()["reports"]) == 1
    assert recovery.load_state()["handover"] is None


def test_reset_can_restore_owned_synthetic_state_with_invalid_chronology():
    state = recovery.replay("stable")
    state["reports"][-1]["date"] = "2026-10-26"
    recovery.STORE_PATH.write_text(json.dumps(state))
    state = recovery.reset()
    assert len(state["reports"]) == 1
    assert state["episode"]["postoperative_day"] == 3


def test_cancelled_extraction_cannot_leave_successful_report(monkeypatch):
    async def run():
        entered = asyncio.Event()
        async def delayed(turns):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(recovery, "extract_live", delayed)
        task = asyncio.create_task(recovery.submit_live("synthetic statement"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert len(recovery.load_state()["reports"]) == 1


def test_stale_request_rejected_before_provider_call(monkeypatch):
    revision = recovery.load_state()["revision"]
    recovery.reset()
    async def unexpected(turns):
        raise AssertionError("Stale work must not call the provider")
    monkeypatch.setattr(recovery, "extract_live", unexpected)
    with pytest.raises(ValueError, match="Demo changed"):
        asyncio.run(recovery.submit_live("synthetic statement", expected_revision=revision))
