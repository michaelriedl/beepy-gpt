import os
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


def test_resume_bg_detects_fork_structurally(stub_claude, tmp_path):
    # No copy note, but the backgrounded id is not the requested session: still a fork.
    stub_claude.set_resume_output("backgrounded · 9ad97bf9\n")
    res = stub_claude.cli().resume_bg("aaaa1111-x", "hi", cwd=str(tmp_path))
    assert res.short_id == "9ad97bf9"
    assert res.forked_as == "9ad97bf9"


def test_resume_bg_dash_led_text_is_refused(stub_claude, tmp_path):
    with pytest.raises(ValueError, match="must not start with '-'"):
        stub_claude.cli().resume_bg("aaaa1111-x", "-p", cwd=str(tmp_path))
    assert stub_claude.calls() == []


def test_missing_cwd_is_reported_as_missing_directory(stub_claude, tmp_path):
    missing = str(tmp_path / "does-not-exist")
    with pytest.raises(ClaudeError, match="working directory is missing"):
        stub_claude.cli().resume_bg("aaaa1111-x", "hi", cwd=missing)
    assert stub_claude.calls() == []


def test_os_error_becomes_claude_error():
    def run(*a, **k):
        raise PermissionError(13, "Permission denied")

    with pytest.raises(ClaudeError, match="could not run.*Permission denied"):
        ClaudeCLI(exe=["claude"], run=run).version()


def test_version(stub_claude):
    assert stub_claude.cli().version() == "2.1.300 (Claude Code)"


def test_timeout_raises_claude_timeout():
    import subprocess

    from beepy_gpt.host.claude_cli import ClaudeTimeout

    def run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    with pytest.raises(ClaudeTimeout) as e:
        ClaudeCLI(run=run).stop("aaaa1111")
    assert isinstance(e.value, ClaudeError) and "timed out" in str(e.value)


def test_find_claude_outside_path():
    from beepy_gpt.host.claude_cli import find_claude

    assert find_claude(which=lambda n: "/opt/bin/claude") == "/opt/bin/claude"
    home_bin = os.path.expanduser("~/.local/bin/claude")
    assert find_claude(which=lambda n: None, is_file=lambda p: p == home_bin) == home_bin
    assert find_claude(which=lambda n: None, is_file=lambda p: False) == "claude"
