import pytest

from beepy_gpt.host.claude_cli import ClaudeCLI, ClaudeError
from helpers import agent

FORK_NOTE = (
    "note: session aaaa1111 is already running in the background, so this started a copy"
    " as 9ad97bf9. `claude attach aaaa1111` opens the original.\n"
    "backgrounded · 9ad97bf9\n"
)


def test_agents_parses_list(stub_claude):
    stub_claude.set_agents([agent(), agent(id="bbbb2222", state="done")])
    out = stub_claude.cli().agents()
    assert [a["id"] for a in out] == ["aaaa1111", "bbbb2222"]
    assert stub_claude.calls()[0]["argv"] == ["agents", "--json"]


def test_agents_all_flag(stub_claude):
    stub_claude.cli().agents(include_all=True)
    assert stub_claude.calls()[0]["argv"] == ["agents", "--json", "--all"]


def test_agents_bad_json(stub_claude):
    stub_claude.set_agents("not-a-list")
    with pytest.raises(ClaudeError, match="expected a list"):
        stub_claude.cli().agents()


def test_nonzero_exit_raises_with_stderr(stub_claude):
    stub_claude.fail(code=3, stderr="Not logged in\n")
    with pytest.raises(ClaudeError, match="Not logged in"):
        stub_claude.cli().version()


def test_missing_executable():
    with pytest.raises(ClaudeError, match="not found"):
        ClaudeCLI(exe=["/nonexistent/claude"]).version()


def test_stop(stub_claude):
    stub_claude.cli().stop("aaaa1111")
    assert stub_claude.calls()[0]["argv"] == ["stop", "aaaa1111"]


def test_resume_bg_uses_no_extra_flags_and_cwd(stub_claude, tmp_path):
    sid = "aaaa1111-0000-4000-8000-000000000000"
    res = stub_claude.cli().resume_bg(sid, "hello", cwd=str(tmp_path))
    call = stub_claude.calls()[0]
    assert call["argv"] == ["--resume", sid, "--bg", "hello"]
    assert call["cwd"] == str(tmp_path)
    assert res.short_id == "aaaa1111" and res.forked_as is None


def test_resume_bg_detects_fork(stub_claude, tmp_path):
    stub_claude.set_resume_output(FORK_NOTE)
    res = stub_claude.cli().resume_bg("aaaa1111-x", "hi", cwd=str(tmp_path))
    assert res.forked_as == "9ad97bf9"


def test_version(stub_claude):
    assert stub_claude.cli().version() == "2.1.300 (Claude Code)"
