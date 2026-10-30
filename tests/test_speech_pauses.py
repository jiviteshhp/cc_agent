"""Output-only pause shortening must preserve speech and streaming boundaries."""
import random
import struct

from browser_voice import SpeechPauseLimiter


def block(value, count=1):
    return struct.pack("<h", value) * (240 * count)


def filtered(chunks):
    limiter = SpeechPauseLimiter()
    return b"".join(limiter.process(chunk) for chunk in chunks) + limiter.finish()


def test_speech_and_short_pauses_are_byte_identical():
    audio = block(1000, 10) + block(0, 25) + block(-1400, 12) + b"\x01\x00"
    assert filtered([audio]) == audio


def test_long_near_silence_is_capped_and_each_voice_onset_is_preserved():
    audio = block(1000, 4) + block(8, 80) + block(-2000, 2) + block(0, 50) + block(1000)
    expected = block(1000, 4) + block(8, 30) + block(-2000, 2) + block(0, 30) + block(1000)
    assert filtered([audio]) == expected


def test_quiet_speech_above_threshold_is_not_removed():
    # Even very quiet non-silent output (peak 17/32768) survives long durations.
    audio = block(17, 100) + block(-17, 100)
    assert filtered([audio]) == audio


def test_tiny_voiced_onset_resets_pause_even_when_most_of_block_is_zero():
    onset = b"\xff\x7f" + b"\0\0" * 239
    audio = block(0, 50) + onset + block(0, 50)
    assert filtered([audio]) == block(0, 30) + onset + block(0, 30)


def test_random_chunk_boundaries_match_whole_clip_and_keep_final_samples():
    audio = block(1000, 3) + block(0, 73) + block(-1000, 5) + b"\x05\x00" * 13
    rng = random.Random(23)
    chunks = []
    offset = 0
    while offset < len(audio):
        size = rng.randint(1, 2000) * 2
        chunks.append(audio[offset:offset + size])
        offset += size
    assert filtered(chunks) == filtered([audio])
    assert filtered(chunks).endswith(b"\x05\x00" * 13)


def test_instances_do_not_carry_silence_state_into_another_reply():
    assert filtered([block(0, 80)]) == block(0, 30)
    assert filtered([block(0, 15)]) == block(0, 15)


def test_output_starts_after_one_block_without_waiting_for_end_of_pause():
    limiter = SpeechPauseLimiter()
    assert limiter.process(block(1000)) == block(1000)
    assert limiter.process(block(0, 30)) == block(0, 30)
    assert limiter.process(block(0, 10)) == b""
    assert limiter.process(block(2000)) == block(2000)
    assert limiter.finish() == b""
