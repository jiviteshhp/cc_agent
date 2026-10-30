import asyncio

import pytest

from browser_speech_gate import BrowserSpeechGate, words
from tests.test_browser_voice import new_agent


def test_hindi_marks_punctuation_and_case_are_tokenized_as_words():
    assert words("  नहीं! मेरी बाईं आँख। STOP ") == ("नहीं", "मेरी", "बाईं", "आँख", "stop")


@pytest.mark.parametrize("value", [None, True, 1, 9, 3.5, "4"])
def test_word_setting_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        BrowserSpeechGate(value)


def test_configurable_word_count_applies_only_to_normal_interruptions():
    gate = BrowserSpeechGate(min_words=4)
    gate.start(0, protected=True)
    assert not gate.consider("मेरी बात सुनिए", .6, final=True)[0]
    assert gate.consider("मेरी बात सुनिए अभी", .7, final=True)[0]
    gate.finish()
    assert gate.min_words == 4
    gate.start(1, protected=True)
    assert gate.consider("रुकिए", 1.3, final=True)[0]
    gate.finish()
    gate.start(2)
    assert gate.consider("हाँ", 2.3, final=True)[0]


def test_website_word_setting_is_snapshotted_for_next_call(monkeypatch):
    import json
    import playground
    monkeypatch.setattr(playground, "configuration", lambda: {"voice_ready":True, "text_ready":True})
    async def run():
        agent = new_agent()
        agent.start_background = lambda: None
        await playground._on_text(agent, json.dumps({"event":"start", "barge_in_min_words":4}))
        assert agent._speech_gate.min_words == 4
        await playground._on_text(agent, json.dumps({"event":"start", "barge_in_min_words":8}))
        assert agent._speech_gate.min_words == 4
        invalid = new_agent()
        await playground._on_text(invalid, json.dumps({"event":"start", "barge_in_min_words":True}))
        assert not invalid.started
    asyncio.run(run())


@pytest.mark.parametrize("text", ["हम्म", "हाँ", "जी", "अच्छा", "hello", "जी जी जी", "hello hello hello", "मेरी आँख"])
def test_short_noise_backchannels_and_repetitions_do_not_interrupt(text):
    gate = BrowserSpeechGate()
    gate.start(0, protected=True)
    assert not gate.consider(text, 1, final=False)[0]
    assert not gate.consider(text, 1.3, final=True)[0]


def test_three_word_partial_requires_duration_and_stability():
    gate = BrowserSpeechGate()
    gate.start(0, protected=True)
    assert not gate.consider("मेरी बात सुनिए", .2, final=False)[0]
    assert not gate.consider("मेरी बात सुनिए", .4, final=False)[0]
    assert gate.consider("मेरी बात सुनिए", .46, final=False)[0]


def test_revised_partial_cannot_borrow_stability_from_different_words():
    gate = BrowserSpeechGate()
    gate.start(0, protected=True)
    gate.consider("मेरी बात सुनिए", .3, final=False)
    assert not gate.consider("मुझे दर्द है", .6, final=False)[0]
    assert gate.consider("मुझे दर्द है अभी", .76, final=False)[0]


@pytest.mark.parametrize("text", ["रुकिए", "नहीं", "STOP!", "wait", "no", "नहीं नहीं"])
def test_deliberate_stop_has_shorter_but_confirmed_path(text):
    gate = BrowserSpeechGate()
    gate.start(0, protected=True)
    assert not gate.consider(text, .1, final=False)[0]
    assert gate.consider(text, .26, final=False)[0]


def test_final_can_confirm_real_speech_but_not_short_vad_click():
    gate = BrowserSpeechGate()
    gate.start(0, protected=True)
    gate.end(.1)
    gate.consider("मेरी बात सुनिए", .2, final=False)
    assert not gate.consider("मेरी बात सुनिए", .8, final=True)[0]
    gate.start(1, protected=True)
    gate.end(1.5)
    assert gate.consider("मेरी बात सुनिए", 1.6, final=True)[0]


def test_missing_vad_needs_stable_recognition_not_one_unprompted_final():
    gate = BrowserSpeechGate()
    assert not gate.consider("मुझे दर्द है", 1, final=True, protected=True)[0]
    assert gate.consider("मुझे दर्द है", 1.46, final=True, protected=True)[0]


@pytest.mark.parametrize("text", ["हाँ", "नहीं", "बाईं", "दो", "जी", "45"])
def test_normal_short_answers_still_work_while_listening(text):
    gate = BrowserSpeechGate()
    gate.start(0)
    gate.end(.3)
    assert gate.consider(text, .5, final=True)[0]


@pytest.mark.parametrize("text", ["नहीं", "नही।", "हाँ", "जी नहीं", "nahi", "no", "yes"])
def test_quick_final_yes_no_is_accepted_after_question(text):
    gate = BrowserSpeechGate(min_words=8)
    gate.start(0)
    gate.end(.16)
    assert gate.consider(text, .3, final=True)[0]


def test_quick_yes_no_exception_does_not_weaken_noise_or_overlap_checks():
    gate = BrowserSpeechGate()
    gate.start(0)
    gate.end(.16)
    assert not gate.consider("नहीं", .3, final=False)[0]
    assert not gate.consider("hello", .4, final=True)[0]
    assert not gate.consider("हम्म", .5, final=True)[0]
    gate.start(1)
    gate.end(1.08)
    assert not gate.consider("नहीं", 1.3, final=True)[0]
    gate.start(2, protected=True)
    gate.end(2.16)
    assert not gate.consider("नहीं", 2.3, final=True, protected=False)[0]
    gate.start(3)
    gate.end(3.16)
    assert not gate.consider("नहीं", 5, final=True)[0]
    gate.finish()
    assert not gate.consider("नहीं", 6, final=False)[0]
    assert not gate.consider("नहीं", 6.16, final=True)[0]


def test_quick_nahi_reaches_answer_handler_after_doctor_question(monkeypatch):
    from unittest.mock import AsyncMock
    import playground

    async def run():
        agent = new_agent()
        agent.state = "listening"
        agent.turn_debounce = 0
        agent.history = [{"role": "assistant", "content": "क्या आपने डॉक्टर को दिखाया है?"}]
        agent._consume_user = AsyncMock()
        agent._on_speech_start()
        agent._speech_gate.started = playground.time.monotonic() - .16
        agent._on_speech_end()
        agent._on_stream_transcript("नहीं")
        await asyncio.gather(*list(agent._tasks), return_exceptions=True)
        agent._consume_user.assert_awaited_once_with("नहीं")
        assert agent._gate_counts["accepted_finals"] == 1
        assert agent._gate_counts["confirmed_interruptions"] == 0
        await agent._close_stream()
    asyncio.run(run())


def test_speech_started_during_playback_does_not_leak_after_playback_finishes():
    gate = BrowserSpeechGate()
    gate.start(0, protected=True)
    gate.end(.6)
    assert not gate.consider("hello", .7, final=True, protected=False)[0]


def test_exact_assistant_echo_is_rejected_but_a_different_answer_survives():
    gate = BrowserSpeechGate()
    gate.start(0, protected=True, reference="बताइए, आपको किस आँख में परेशानी है?")
    assert gate.consider("किस आँख में परेशानी है", .6, final=True) == (False, "assistant_echo")
    assert gate.consider("मेरी बाईं आँख में", .7, final=True)[0]


def test_echo_reference_tracks_text_generated_after_speech_started():
    gate = BrowserSpeechGate()
    gate.start(0, protected=True, reference="अच्छा।")
    assert gate.consider("यह कब से है", .6, final=True,
                         reference="अच्छा। यह कब से है?") == (False, "assistant_echo")


def test_speakerphone_scenario_noise_echo_real_stop_then_short_answer():
    gate = BrowserSpeechGate()
    # Simulated recognition events, not an acoustic benchmark.
    for text in ("हम्म", "जी जी जी", "hello"):
        gate.start(0, protected=True)
        gate.end(.6)
        assert not gate.consider(text, .7, final=True)[0]
        gate.finish()
    gate.start(1, protected=True, reference="यह कब से है?")
    assert not gate.consider("यह कब से है", 1.6, final=True)[0]
    gate.finish()
    gate.start(2, protected=True)
    gate.consider("रुकिए", 2.1, final=False)
    assert gate.consider("रुकिए", 2.3, final=False)[0]
    gate.finish()
    gate.start(3)
    gate.end(3.3)
    assert gate.consider("हाँ", 3.4, final=True)[0]


def test_old_vad_and_repeated_start_do_not_create_unbounded_confirmation():
    gate = BrowserSpeechGate()
    gate.start(0, protected=True)
    gate.start(.3, protected=True)
    gate.end(.5)
    assert gate.consider("मेरी बात सुनिए", .6, final=True)[0]
    gate.finish()
    assert not gate.consider("मेरी बात सुनिए", 10, final=True)[0]
    gate.start(11)
    gate.end(11.3)
    assert not gate.consider("हाँ", 14, final=True)[0]


def test_rejected_final_cannot_start_reply_or_enter_history_even_after_playback():
    async def run():
        agent = new_agent()
        agent.state = "speaking"
        agent._on_speech_start()
        agent._speech_gate.started -= .6
        agent._on_speech_end()
        agent._after_speaking()
        agent._on_stream_transcript("hello")
        await asyncio.gather(*list(agent._tasks), return_exceptions=True)
        assert not agent._pending and not agent.history and not agent._interrupt
        assert not any(e["type"] in ("user", "final_fragment", "bot_start") for e in agent.ws.events)
        assert agent._gate_counts["rejected_finals"] == 1
        await agent._close_stream()
    asyncio.run(run())


def test_rejected_idle_hallucination_does_not_start_a_reply():
    async def run():
        agent = new_agent()
        agent.state = "listening"
        await agent._handle_stream_text("some phantom words")
        assert not agent.history and not agent._pending
        await agent._close_stream()
    asyncio.run(run())


def test_confirmed_phrase_stops_generation_once_and_final_is_retained():
    from unittest.mock import AsyncMock

    async def run():
        agent = new_agent()
        agent.state = "speaking"
        agent.turn_debounce = 0
        agent._consume_user = AsyncMock()
        agent._generation_task = asyncio.create_task(asyncio.sleep(10))
        agent._on_speech_start()
        agent._speech_gate.started -= .6
        agent._on_partial("मेरी बात सुनिए")
        assert not agent._interrupt
        agent._speech_gate.anchor_at -= .2
        agent._on_partial("मेरी बात सुनिए अभी")
        await asyncio.gather(agent._generation_task, return_exceptions=True)
        await agent._clear_task
        agent._on_speech_end()
        agent._on_stream_transcript("मेरी बात सुनिए अभी")
        await asyncio.gather(*list(agent._tasks), return_exceptions=True)
        assert sum(e["type"] == "clear" for e in agent.ws.events) == 1
        assert agent._gate_counts["confirmed_interruptions"] == 1
        agent._consume_user.assert_awaited_once_with("मेरी बात सुनिए अभी")
        await agent._close_stream()
    asyncio.run(run())
