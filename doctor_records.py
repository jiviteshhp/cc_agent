"""Prepared source records for the doctor's local presentation workspace.

This case is deliberately separate from incoming telephone sessions and existing
care stores. Its transcript and clinical history are prepared content. Only local
staff actions and administrative room edits are persisted here. No external
notification, telephone call or clinician approval is implied.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from uuid import uuid4

import recovery

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "doctor" / "prepared_case.json"
STORE_PATH = Path(os.getenv("DOCTOR_PREPARED_STATE_PATH", "state/doctor-prepared.json"))
OWNER = "doctor-prepared-case-v1"
CASE_ID = "doctor-prepared-case-001"
_LOCK = threading.RLock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def prepared_case():
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if case.get("id") != CASE_ID or case.get("provenance") != "Prepared case":
        raise ValueError("Prepared case source is unavailable")
    validate_report_evidence(case["report"])
    return case


def validate_report_evidence(report):
    """Fail closed if a source field cites absent or non-patient words."""
    turns = report.get("turns", [])
    source = {turn.get("id"): turn for turn in turns if isinstance(turn, dict)}
    if len(source) != len(turns) or None in source:
        raise ValueError("Report transcript has invalid turn identifiers")
    for field in report.get("fields", []):
        if not isinstance(field, dict) or not field.get("evidence"):
            raise ValueError("Report field has no supporting patient source")
        for ref in field["evidence"]:
            turn = source.get(ref.get("turn_id")) if isinstance(ref, dict) else None
            quote = ref.get("quote") if isinstance(ref, dict) else None
            if (not turn or turn.get("role") != "patient" or not isinstance(quote, str)
                    or not quote.strip() or quote not in turn.get("text", "")):
                raise ValueError("Report field evidence could not be verified")


def _initial_state():
    return {"owner": OWNER, "case_id": CASE_ID, "revision": 0,
            "acknowledgement": None, "disposition": None,
            "routing": None, "audit": []}


def _load():
    if not STORE_PATH.exists():
        return _initial_state()
    state = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("owner") != OWNER
            or state.get("case_id") != CASE_ID
            or type(state.get("revision")) is not int or state["revision"] < 0):
        raise ValueError("Refusing to use an unrelated workspace record")
    return state


def _save(state):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STORE_PATH.with_name(STORE_PATH.name + ".tmp-" + uuid4().hex)
    try:
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, STORE_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def _check_revision(state, expected_revision):
    if expected_revision is not None and expected_revision != state["revision"]:
        raise ValueError("This record changed. Refresh before saving your action.")


def _staff_name(staff):
    if not isinstance(staff, str) or not staff.strip() or len(staff.strip()) > 100:
        raise ValueError("Enter a staff name to record this action")
    return staff.strip()


def _routing(case, state):
    route = deepcopy(case["routing"])
    changes = state.get("routing")
    if changes:
        route["steps"][0]["room"] = changes["vision_room"]
        route["steps"][1]["room"] = changes["nct_room"]
        route["updated_by"] = changes["staff"]
        route["updated_at"] = changes["at"]
    return route


def _recovery_call(call, procedure):
    # Existing core requires assistant role for the agent's transcript turns.
    core_turns = [{**turn, "role": "assistant" if turn["role"] == "agent" else turn["role"]}
                  for turn in call["turns"]]
    observations, decision = recovery.evaluate_rules(core_turns, call["extraction"])
    worsened = [obs for obs in observations if obs["change"] == "worse" and not obs.get("superseded_by")]
    if worsened:
        summary = "Patient reports " + " and ".join(
            "increased pain" if obs["symptom"] == "pain" else "worse seeing"
            for obs in worsened) + " since the previous follow-up."
    elif decision["status"] == "review_requested":
        summary = "Report requires review because information is missing, uncertain or unsupported."
    else:
        summary = "No worsening reported. Scheduled clinician review remains unchanged."
    return {"id": call["id"], "date": call["date"], "label": call["label"],
            "summary": summary, "turns": [{**turn, "audio": None} for turn in call["turns"]],
            "observations": observations, "decision": decision,
            "status": "record_available", "source": "Prepared case",
            "extraction_source": "Prepared extraction; exact evidence validated",
            "postoperative_day": recovery.postoperative_day(procedure["date"], call["date"]),
            "audio_available": False,
            "audio_note": "Audio unavailable for this prepared record.",
            "external_call": "not_attempted"}


def _workspace(case, state):
    report = deepcopy(case["report"])
    report.update(patient=deepcopy(case["patient"]), provenance=case["provenance"],
                  source="Prepared patient conversation", extraction_source="Prepared extraction",
                  routing=_routing(case, state),
                  pdf_url="/doctor/api/reports/prepared/pdf",
                  visit_pdf_url="/doctor/api/reports/prepared/visit.pdf",
                  audio_available=False,
                  audio_note="Audio unavailable for this prepared record.")
    procedure = deepcopy(case["procedure"])
    calls = [_recovery_call(call, procedure) for call in case["calls"]]
    procedure["postoperative_day"] = recovery.postoperative_day(procedure["date"], calls[-1]["date"])
    last = calls[-1]
    protocol = recovery.protocol()
    matched = [rule for rule in protocol["rules"] if rule["id"] in last["decision"]["criterion_ids"]]
    handover = None
    notification = None
    if last["decision"]["status"] == "review_requested":
        acknowledgement = state.get("acknowledgement")
        disposition = state.get("disposition")
        handover = {
            "id": "review-prepared-001",
            "status": "disposition_recorded" if disposition else "acknowledged" if acknowledgement else "review_requested",
            "criterion": matched[0]["label"] if matched else "Patient report requires review",
            "criteria": [{"id": rule["id"], "label": rule["label"], "condition": rule["condition"]} for rule in matched],
            "protocol_version": protocol["version"],
            "protocol_version_label": "0.1.0 (illustrative)",
            "protocol_approval": "Illustrative content; clinical-owner approval required",
            "evidence": [{"report_id": last["id"], **ref}
                         for obs in last["observations"]
                         if obs["change"] == "worse" and not obs.get("superseded_by")
                         for ref in obs["evidence"]],
            "requested_at": last["date"] + "T09:00:00+05:30",
            "requested_at_source": "Prepared case chronology",
            "acknowledged_at": acknowledgement["at"] if acknowledgement else None,
            "staff": acknowledgement["staff"] if acknowledgement else None,
            "disposition": disposition,
            "resolution": "not_recorded",
            "external_delivery": "not_attempted",
            "transfer_status": "not_attempted",
            "issues": last["decision"]["issues"],
        }
        notification = {
            "id": "notification-prepared-001", "channel": "doctor_portal",
            "title": "Patient report needs your review", "message": last["summary"],
            "status": "acknowledged" if acknowledgement else "unread",
            "handover_id": handover["id"], "external_delivery": "not_attempted",
            "source": "Prepared case",
        }
    aftercare = {"patient": deepcopy(case["patient"]), "procedure": procedure,
                 "calls": calls, "handover": handover, "notification": notification,
                 "provenance": case["provenance"], "clinical_clearance": False,
                 "scheduled_care": "unchanged", "scheduled_review_date": procedure["discharge"]["scheduled_review_date"],
                 "audit": deepcopy(state["audit"])}
    return {"report": report, "aftercare": aftercare, "revision": state["revision"]}


def workspace():
    with _LOCK:
        return _workspace(prepared_case(), _load())


def acknowledge(staff, expected_revision=None):
    with _LOCK:
        staff = _staff_name(staff)
        case, state = prepared_case(), _load()
        _check_revision(state, expected_revision)
        if _workspace(case, state)["aftercare"]["handover"] is None:
            raise ValueError("No review request is available to acknowledge")
        if state["acknowledgement"]:
            return _workspace(case, state)
        action = {"staff": staff, "at": _now()}
        state["acknowledgement"] = action
        state["revision"] += 1
        state["audit"].append({"action": "acknowledged", **action,
                               "note": "Review acknowledged; clinical resolution is not recorded."})
        _save(state)
        return _workspace(case, state)


def record_disposition(staff, note, expected_revision=None):
    with _LOCK:
        staff = _staff_name(staff)
        if not isinstance(note, str) or not note.strip() or len(note.strip()) > 2000:
            raise ValueError("Enter the clinician's next step before saving a disposition")
        case, state = prepared_case(), _load()
        _check_revision(state, expected_revision)
        if not state["acknowledgement"]:
            raise ValueError("Acknowledge the review request before recording a disposition")
        action = {"staff": staff, "at": _now(), "note": note.strip()}
        state["disposition"] = action
        state["revision"] += 1
        state["audit"].append({"action": "disposition_recorded", **action})
        _save(state)
        return _workspace(case, state)


def update_routing(staff, vision_room, nct_room, expected_revision=None):
    with _LOCK:
        staff = _staff_name(staff)
        rooms = []
        for room in (vision_room, nct_room):
            if not isinstance(room, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /-]{0,39}", room.strip()):
                raise ValueError("Enter a room number or short room label")
            rooms.append(room.strip())
        case, state = prepared_case(), _load()
        _check_revision(state, expected_revision)
        action = {"staff": staff, "at": _now(), "vision_room": rooms[0], "nct_room": rooms[1]}
        state["routing"] = action
        state["revision"] += 1
        state["audit"].append({"action": "rooms_updated", **action})
        _save(state)
        return _workspace(case, state)


def reset_prepared(expected_revision=None):
    """Reset only the store whose owner and case markers match this module."""
    with _LOCK:
        old = _load()
        _check_revision(old, expected_revision)
        state = _initial_state()
        state["revision"] = old["revision"] + 1
        state["audit"] = [{"action": "prepared_case_reset", "at": _now(),
                           "staff": "Workspace operator", "note": "Only prepared-case actions and room edits reset."}]
        _save(state)
        return _workspace(prepared_case(), state)


def report_pdf():
    from visit_slip import generate_report
    return generate_report(workspace()["report"])


def visit_pdf():
    from visit_slip import generate_visit
    return generate_visit(workspace()["report"])
