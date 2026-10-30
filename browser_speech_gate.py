"""Shared transcript admission for hands-free calls; no provider/clinical logic."""
import unicodedata


def words(text):
    # Keep Devanagari vowel marks; \w-based tokenizers split Hindi syllables.
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple("".join(ch if unicodedata.category(ch)[0] in "LMN" else " "
                         for ch in normalized).split())


STOPS = frozenset(("रुकिए", "रुकिये", "रुको", "रुकें", "बस", "नहीं", "नही",
                   "stop", "wait", "no", "nahi", "nahin", "ruko", "rukiye"))
FILLERS = frozenset(("हम्म", "हूँ", "हूं", "हं", "hmm", "hm", "um", "uh"))
BACKCHANNELS = FILLERS | frozenset(("हाँ", "हां", "जी", "अच्छा", "ओके", "okay", "ok", "yes"))
SHORT_ANSWERS = frozenset(words(text) for text in (
    "नहीं", "नही", "हाँ", "हां", "nahi", "nahin", "haan", "han", "yes", "no",
    "जी नहीं", "जी नही", "जी हाँ", "जी हां",
))


class BrowserSpeechGate:
    """Require recognition confirmation plus fresh speech evidence.

    During playback: configurable 2–8 words (default 3)/450 ms, or a deliberate stop/250 ms. Partials
    must retain the same prefix for 150 ms; a final provides confirmation.
    While listening: final yes/no answers need 150 ms of fresh VAD evidence;
    other answers and the missing-VAD fallback still need 250 ms.
    Missing VAD can be replaced by consistent recognition over that duration.
    No timer alone accepts text. Rejected finals never become conversation turns.
    """
    def __init__(self, min_words=3):
        if type(min_words) is not int or not 2 <= min_words <= 8:
            raise ValueError("Minimum interruption words must be an integer from 2 to 8")
        self.min_words = min_words
        self.reset()

    def reset(self):
        self.started = self.ended = None
        self.protected = False
        self.anchor = ()
        self.anchor_at = self.last_text_at = None
        self.reference = ()

    def start(self, now, protected=False, reference=""):
        # Duplicate starts must not keep postponing a genuine interruption.
        if self.started is not None and self.ended is None:
            return
        self.reset()
        self.started = now
        self.protected = protected
        self.reference = words(reference)

    def end(self, now):
        if self.started is not None:
            self.ended = now

    def consider(self, text, now, *, final, protected=False, reference=""):
        tokens = words(text)
        self.protected |= protected
        # Assistant text continues to grow during a VAD segment. Compare against
        # the latest reference, retaining the old one when playback just ended.
        if reference:
            self.reference = words(reference)
        if not tokens or all(token in FILLERS for token in tokens):
            return False, "empty_or_filler"
        # Exact phrase matching only, not fuzzy matching against historical calls.
        if len(tokens) >= 3 and any(
            self.reference[i:i + len(tokens)] == tokens
            for i in range(len(self.reference) - len(tokens) + 1)
        ):
            return False, "assistant_echo"
        stop = all(token in STOPS for token in tokens)
        if self.protected and not stop:
            if len(tokens) < self.min_words or len(set(tokens)) < 2 or all(t in BACKCHANNELS for t in tokens):
                return False, "too_short_during_reply"

        anchor = tokens if stop else tokens[:self.min_words if self.protected else 3]
        if anchor != self.anchor or self.last_text_at is None or now - self.last_text_at > 1.5:
            self.anchor, self.anchor_at = anchor, now
        stable = now - self.anchor_at
        self.last_text_at = now
        duration = 0.0
        if self.started is not None and (self.ended is None or now - self.ended <= 1.5):
            duration = (self.ended if self.ended is not None else now) - self.started
        required = .45 if self.protected and not stop else .25
        # A quick answer to a finished question is not a barge-in. Only relax
        # final yes/no recognition with observed VAD, never partials, overlap,
        # missing VAD, or arbitrary one-word noise.
        if final and not self.protected and self.started is not None and tokens in SHORT_ANSWERS:
            required = .15
        # Stable text is a fallback for MISSING VAD, not permission to override
        # a known short noise burst or stale speech-end event.
        evidence = duration if self.started is not None else stable
        if evidence + 1e-9 < required:
            return False, "insufficient_speech"
        if not final and stable + 1e-9 < .15:
            return False, "unconfirmed_partial"
        return True, "stop" if stop else "speech"

    def finish(self):
        self.reset()
