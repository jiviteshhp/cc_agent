import asyncio

import main


class SyntheticFormRequest:
    def __init__(self, form):
        self._form = form

    async def form(self):
        return self._form


def test_answer_returns_vobiz_bidirectional_stream(monkeypatch, synthetic_scenarios):
    patient = synthetic_scenarios[0]["patient"]
    monkeypatch.setenv("SERVER_HOST", "voice.test.invalid")
    monkeypatch.setenv("NOISE_CANCELLATION", "true")
    monkeypatch.setenv("NOISE_CANCELLATION_LEVEL", "40")

    response = asyncio.run(main.answer(SyntheticFormRequest({"From": patient["phone"]})))
    xml = response.body.decode("utf-8")

    assert response.status_code == 200
    assert response.media_type == "application/xml"
    assert 'bidirectional="true"' in xml
    assert 'keepCallAlive="true"' in xml
    assert 'noiseCancellation="true"' in xml
    assert 'noiseCancellationLevel="40"' in xml
    assert "wss://voice.test.invalid/stream?phone=%2B000000000001" in xml
