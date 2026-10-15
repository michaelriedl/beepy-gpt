import json
from pathlib import Path

from beepy_gpt.host.transcripts import (
    FeedEvent,
    parse_entry,
    read_events,
    set_claude_version,
    summarize_tool,
    transcript_path,
)

FIXTURE = Path(__file__).parent / "fixtures" / "transcript_basic.jsonl"


def test_basic_fixture_events():
    events, offset = read_events(FIXTURE)
    assert offset == FIXTURE.stat().st_size
    assert events == [
        FeedEvent("you", "Run the parser tests"),
        FeedEvent("claude", "Running them now."),
        FeedEvent("tool_call", "$ pytest -q tests/test_parser.py …"),
        FeedEvent("tool_result", "3 passed in 0.12s", True),
        FeedEvent("tool_call", "Read /home/dev/projects/parser/README.md"),
        FeedEvent("tool_result", "File not found", False),
        FeedEvent("tool_call", "$ make all"),
        FeedEvent("interrupted", "interrupted"),
        FeedEvent("unknown", "widget"),
        FeedEvent("claude", "All done."),
    ]


def test_incremental_read_from_offset(tmp_path):
    p = tmp_path / "t.jsonl"
    lines = FIXTURE.read_text().splitlines(keepends=True)
    p.write_text("".join(lines[:2]))
    first, off = read_events(p)
    with p.open("a") as f:
        f.write("".join(lines[2:]))
    rest, off2 = read_events(p, off)
    assert first == [FeedEvent("you", "Run the parser tests")]
    assert rest[0] == FeedEvent("claude", "Running them now.")
    assert off2 == p.stat().st_size


def test_partial_trailing_line_is_read_later(tmp_path):
    p = tmp_path / "t.jsonl"
    full = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "late"}]}})
    p.write_text(
        json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n" + full[:10]
    )
    events, off = read_events(p)
    assert events == [FeedEvent("you", "hi")]
    with p.open("a") as f:
        f.write(full[10:] + "\n")
    events2, off2 = read_events(p, off)
    assert events2 == [FeedEvent("claude", "late")]
    again, _ = read_events(p, off2)
    assert again == []


def test_bad_json_line_is_unknown(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("{broken\n")
    assert read_events(p)[0] == [FeedEvent("unknown", "unreadable line")]


def test_missing_file_and_shrink(tmp_path):
    p = tmp_path / "t.jsonl"
    assert read_events(p, 5) == ([], 5)
    p.write_text(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
    events, _ = read_events(p, 10_000)
    assert events == [FeedEvent("you", "x")]


def test_summarize_tool():
    assert summarize_tool("Bash", {"command": "ls"}) == "$ ls"
    assert summarize_tool("Grep", {"pattern": "TODO"}) == "Grep TODO"
    assert summarize_tool("Mystery", {}) == "Mystery"
    assert len(summarize_tool("Bash", {"command": "x" * 500})) == 200


def test_transcript_path():
    p = transcript_path(Path("/h/.claude"), "/home/dev/my.proj", "sid")
    assert p == Path("/h/.claude/projects/-home-dev-my-proj/sid.jsonl")


def test_unknown_block_warning_names_claude_version(caplog):
    set_claude_version("2.1.300 (Claude Code)")
    assert parse_entry({"type": "assistant", "message": {"content": [{"type": "gizmo"}]}}) == [
        FeedEvent("unknown", "gizmo")
    ]
    msgs = [r.getMessage() for r in caplog.records]
    assert any("'gizmo'" in m and "2.1.300" in m for m in msgs)


def test_non_dict_message_does_not_wedge_the_feed(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        json.dumps({"type": "user", "message": "plain string"}) + "\n"
        + json.dumps({"type": "assistant", "message": ["a", "list"]}) + "\n"
        + json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
    )
    events, offset = read_events(p)
    assert offset == p.stat().st_size
    assert events == [FeedEvent("unknown", "user entry"), FeedEvent("unknown", "assistant entry"), FeedEvent("you", "hello")]
