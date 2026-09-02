def test_all_fixtures_are_clearly_synthetic(synthetic_scenarios):
    assert synthetic_scenarios
    for scenario in synthetic_scenarios:
        patient = scenario["patient"]
        assert scenario["id"]
        assert patient["name"].startswith("Synthetic Patient ")
        assert patient["uhid"].startswith("SYNTH-")
        assert patient["phone"].startswith("+000000")
        assert "expected" in scenario
