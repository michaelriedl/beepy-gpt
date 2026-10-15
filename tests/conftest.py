import json
import sys
from pathlib import Path

import pytest

from beepy_gpt.host.claude_cli import ClaudeCLI

STUBS = Path(__file__).parent / "stubs"


class StubClaude:
    def __init__(self, root: Path):
        self.root = root

    def set_agents(self, *responses):
        (self.root / "agents_seq.json").write_text(json.dumps(list(responses)))

    def set_resume_output(self, text):
        (self.root / "resume.txt").write_text(text)

    def fail(self, code=1, stderr="boom"):
        (self.root / "exit_code").write_text(str(code))
        (self.root / "stderr.txt").write_text(stderr)

    def calls(self):
        log = self.root / "calls.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def cli(self) -> ClaudeCLI:
        return ClaudeCLI(exe=[sys.executable, str(STUBS / "claude_stub.py"), str(self.root)])


@pytest.fixture
def stub_claude(tmp_path):
    d = tmp_path / "stub"
    d.mkdir()
    return StubClaude(d)


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock():
    return FakeClock()
