import re

import session_manager


def _use_temporary_session_directory(monkeypatch, tmp_path):
    directory = tmp_path / "sessions"
    monkeypatch.setattr(session_manager, "SESSIONS_DIR", str(directory))
    return directory


def test_session_round_trip_and_incrementing_ids(monkeypatch, tmp_path, synthetic_scenarios):
    directory = _use_temporary_session_directory(monkeypatch, tmp_path)
    first_patient = synthetic_scenarios[0]["patient"]
    second_patient = synthetic_scenarios[1]["patient"]

    first = session_manager.new_session(**first_patient)
    second = session_manager.new_session(**second_patient)

    assert re.fullmatch(r"\d{8}-0001", first["session_id"])
    assert re.fullmatch(r"\d{8}-0002", second["session_id"])
    assert first["status"] == "registered"
    assert first["phone"] == first_patient["phone"]
    assert session_manager.load_session(first["session_id"]) == first
    assert len(list(directory.glob("*.json"))) == 2


def test_phone_lookup_prefers_registered_session(monkeypatch, tmp_path, synthetic_scenarios):
    _use_temporary_session_directory(monkeypatch, tmp_path)
    patient = synthetic_scenarios[0]["patient"]

    completed = session_manager.new_session(**patient)
    completed["status"] = "complete"
    completed["created_at"] = "2026-09-02T10:00:00"
    session_manager.save_session(completed)

    registered = session_manager.new_session(**patient)
    registered["created_at"] = "2026-09-02T09:00:00"
    session_manager.save_session(registered)

    found = session_manager.find_session_by_phone("00000 00001")

    assert found["session_id"] == registered["session_id"]
    assert found["status"] == "registered"
