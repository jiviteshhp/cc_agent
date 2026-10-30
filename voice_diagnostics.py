"""Content-free voice diagnostics. Never serialize exceptions or provider payloads."""
import asyncio
import json
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("voice_diagnostic", default=None)
_CODES = frozenset({
    "rate_limit_exceeded_error", "insufficient_quota_error", "invalid_api_key",
    "invalid_request_error", "internal_server_error", "authentication_error",
    "invalid_api_key_error", "unprocessable_entity_error", "not_found_error",
    "RESOURCE_EXHAUSTED", "UNAUTHENTICATED", "PERMISSION_DENIED",
    "INVALID_ARGUMENT", "UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED",
})

# Only known opaque identifier shapes, never arbitrary provider strings.
_REQUEST_ID = re.compile(r"(?:\d{8}_)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32}|req_[0-9a-fA-F]{16,64}")
_FIELDS = frozenset({'text', 'speaker', 'model', 'language_code', 'target_language_code',
    'speech_sample_rate', 'output_audio_codec', 'pace', 'temperature', 'min_buffer_size',
    'max_chunk_length', 'type'})
_VALIDATION_TYPES = frozenset({'missing', 'string_type', 'string_too_short', 'string_too_long',
    'literal_error', 'enum', 'greater_than_equal', 'less_than_equal', 'finite_number',
    'int_parsing', 'float_parsing', 'value_error', 'extra_forbidden'})


def provider_error_details(payload):
    """Extract structured metadata only; never retain raw messages or payloads.

    Cover top-level, data, error and data.error envelopes. Unknown codes and
    unsupported identifier shapes are flagged instead of silently disappearing.
    """
    if not isinstance(payload, dict):
        return {"provider_code_state": "missing"}
    nodes = [payload]
    for node in list(nodes):
        for key in ("data", "error"):
            if isinstance(node.get(key), dict):
                nodes.append(node[key])
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        nodes.append(data["error"])
    details = {}
    codes = [node[key] for node in nodes for key in ("code", "error_code") if key in node]
    for value in codes:
        if isinstance(value, str) and value in _CODES:
            details["provider_code"] = value
            break
    if "provider_code" not in details:
        details["provider_code_state"] = "unrecognized" if codes else "missing"
    for node in nodes:
        # Pydantic-style validation metadata only. Never retain msg/input/ctx.
        for key in ('detail', 'details', 'errors'):
            errors = node.get(key)
            if isinstance(errors, list):
                for error in errors[:8]:
                    if not isinstance(error, dict):
                        continue
                    loc = error.get('loc', [])
                    if isinstance(loc, list):
                        fields = [x for x in loc if isinstance(x, str) and x in _FIELDS]
                        if fields:
                            details.setdefault('validation_fields', [])
                            details['validation_fields'] = sorted(set(details['validation_fields'] + fields))[:8]
                    kind = error.get('type')
                    if isinstance(kind, str) and kind in _VALIDATION_TYPES:
                        details.setdefault('validation_types', [])
                        details['validation_types'] = sorted(set(details['validation_types'] + [kind]))[:8]
        for key in ("status_code", "http_status", "status", "code"):
            value = node.get(key)
            if type(value) is int and 400 <= value <= 599:
                details.setdefault("http_status", value)
        if "request_id" in node:
            value = node["request_id"]
            if isinstance(value, str) and len(value) <= 80 and _REQUEST_ID.fullmatch(value):
                details.setdefault("provider_request_id", value)
            else:
                details["provider_request_id_state"] = "redacted"
    if "provider_request_id" in details:
        details.pop("provider_request_id_state", None)
    return details


def error_details(exc, code=None):
    # Allowlisting is intentional: even an apparently harmless provider code or
    # exception message can contain submitted text, URLs or credentials.
    details = {}
    # Our TTS exception carries only metadata already filtered above.
    stored = getattr(exc, "provider_details", None)
    if isinstance(stored, dict):
        details.update(stored)
    response = getattr(exc, "response", None)
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, str)) and len(body) <= 65536:
        try:
            details.update(provider_error_details(json.loads(body)))
        except (ValueError, UnicodeError):
            pass
    # WebSocket close codes are not HTTP codes (and .code is deprecated there).
    api_code = None if hasattr(exc, "rcvd") else getattr(exc, "code", None)
    for value in (api_code, getattr(exc, "status_code", None),
                  getattr(getattr(exc, "response", None), "status_code", None)):
        if type(value) is int and 100 <= value <= 599:
            details["http_status"] = value
            break
    for value in (code, getattr(exc, "status", None), api_code):
        if isinstance(value, str) and value in _CODES:
            details["provider_code"] = value
            break
    if "provider_code" in details:
        details.pop("provider_code_state", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        for key in ("x-request-id", "request-id"):
            value = headers.get(key)
            if isinstance(value, str) and len(value) <= 80 and _REQUEST_ID.fullmatch(value):
                details.setdefault("provider_request_id", value)
    received = getattr(exc, "rcvd", None)
    close_code = getattr(received, "code", None)
    if type(close_code) is int and 1000 <= close_code <= 4999:
        details["close_code"] = close_code
    status = details.get("http_status")
    provider_code = details.get("provider_code")
    if status in (401, 403) or provider_code in {"invalid_api_key", "invalid_api_key_error", "authentication_error", "UNAUTHENTICATED", "PERMISSION_DENIED"}:
        category = "authentication_or_access"
    elif status == 402 or provider_code == "insufficient_quota_error":
        category = "credits_exhausted"
    elif provider_code == "rate_limit_exceeded_error":
        category = "rate_limited"
    elif status == 429 or provider_code == "RESOURCE_EXHAUSTED":
        category = "quota_or_rate_limit"
    elif (status and status >= 500) or provider_code in {"internal_server_error", "UNAVAILABLE", "INTERNAL"}:
        category = "provider_server"
    elif isinstance(exc, TimeoutError):
        category = "timeout"
    elif "close_code" in details or isinstance(exc, ConnectionError):
        category = "connection"
    elif (status in (400, 404, 413, 422) or provider_code in {
            "invalid_request_error", "unprocessable_entity_error", "not_found_error", "INVALID_ARGUMENT"}
            or isinstance(exc, (ValueError, KeyError, TypeError))):
        category = "invalid_data_or_configuration"
    else:
        category = {"EmptyModelResponse": "empty_response",
                    "SpeechSynthesisUnavailable": "provider_rejected",
                    "STTUnavailable": "provider_rejected"}.get(
                        type(exc).__name__, "provider_or_application")
    return {"category": category, **details}


def write_event(data):
    print("[voice_diagnostic] " + json.dumps({"version": 1, **data}), flush=True)


class TurnDiagnostic:
    def __init__(self, call, turn, operation):
        self.call, self.turn, self.operation = call, turn, operation
        self.started = time.monotonic()
        self.failure = None
        self.outcome = "completed"
        self.interruption = None
        self.text_chars = self.audio_bytes = 0
        self.first_text_ms = self.first_audio_ms = None
        self.tts_chunks = self.tts_max_chars = self.tts_audio_chunks = 0
        self.tts_max_gap_ms = 0
        self._last_tts_audio = None

    def tts_text(self, text):
        self.tts_chunks += 1
        self.tts_max_chars = max(self.tts_max_chars, len(text))

    def tts_audio(self):
        now = time.monotonic()
        self.tts_audio_chunks += 1
        if self._last_tts_audio is not None:
            self.tts_max_gap_ms = max(self.tts_max_gap_ms, round((now - self._last_tts_audio) * 1000))
        self._last_tts_audio = now

    def text(self, text):
        if self.first_text_ms is None:
            self.first_text_ms = round((time.monotonic() - self.started) * 1000)
        self.text_chars += len(text)

    def audio(self, size):
        if self.first_audio_ms is None:
            self.first_audio_ms = round((time.monotonic() - self.started) * 1000)
        self.audio_bytes += size


def report_failure(component, stage, exc, code=None):
    failure = {"component": component, "stage": stage, **error_details(exc, code)}
    current = _current.get()
    if current is None:
        write_event({"event": "failure", **failure})
    elif current.failure is None:
        # An LLM exception propagates through the TTS sender: keep its origin.
        current.failure = failure
        current.outcome = "failed"


def current():
    return _current.get()


@contextmanager
def turn(call, number, operation):
    diagnostic = TurnDiagnostic(call, number, operation)
    token = _current.set(diagnostic)
    try:
        yield diagnostic
    except asyncio.CancelledError:
        diagnostic.outcome = "cancelled"
        raise
    except Exception as exc:
        report_failure("application", operation, exc)
        raise
    finally:
        _current.reset(token)
        write_event({"event": "turn", "call": call, "turn": number,
                     "operation": operation, "outcome": diagnostic.outcome,
                     "interruption": diagnostic.interruption,
                     "elapsed_ms": round((time.monotonic() - diagnostic.started) * 1000),
                     "text_chars": diagnostic.text_chars,
                     "audio_bytes_sent": diagnostic.audio_bytes,
                     "first_text_ms": diagnostic.first_text_ms,
                     "first_audio_sent_ms": diagnostic.first_audio_ms,
                     "tts_text_chunks": diagnostic.tts_chunks,
                     "tts_max_text_chars": diagnostic.tts_max_chars,
                     "tts_audio_chunks": diagnostic.tts_audio_chunks,
                     "tts_max_receive_gap_ms": diagnostic.tts_max_gap_ms,
                     "failure": diagnostic.failure})
