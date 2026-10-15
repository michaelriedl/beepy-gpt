import json

import pytest

from beepy_gpt.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    decode,
    encode,
    response_error,
    response_ok,
)


def test_encode_adds_version_and_newline():
    line = encode({"type": "hello", "id": 0})
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line) == {"v": PROTOCOL_VERSION, "type": "hello", "id": 0}


def test_encode_overrides_caller_version():
    assert json.loads(encode({"type": "x", "v": 99}))["v"] == PROTOCOL_VERSION


def test_encode_keeps_unicode_unescaped():
    assert "ö ✓" in encode({"type": "x", "text": "ö ✓"})


def test_encode_requires_type():
    with pytest.raises(ProtocolError):
        encode({"id": 1})


def test_roundtrip():
    msg = {"type": "reply", "id": 3, "session_id": "abc", "text": "hi"}
    assert decode(encode(msg)) == {**msg, "v": PROTOCOL_VERSION}


@pytest.mark.parametrize("line", ["not json", "[1,2]", '{"id": 1}', '{"type": 5}'])
def test_decode_rejects_bad_lines(line):
    with pytest.raises(ProtocolError):
        decode(line)


def test_response_helpers():
    assert response_ok(4, x=1) == {"type": "response", "id": 4, "ok": True, "x": 1}
    assert response_error(4, "nope", "msg") == {
        "type": "response",
        "id": 4,
        "ok": False,
        "error": {"code": "nope", "message": "msg"},
    }
