import json

import pytest

from beepy_gpt.host.install import (
    hook_installed,
    load_settings,
    plan_install,
    plan_uninstall,
    run_change,
)

CMD = "/home/dev/.local/bin/bgpt-host hook"


def test_install_adds_entry_and_keeps_other_keys():
    settings = {"theme": "dark", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}
    new = plan_install(settings, CMD, 630)
    assert new["theme"] == "dark" and new["hooks"]["Stop"] == settings["hooks"]["Stop"]
    assert new["hooks"]["PermissionRequest"] == [
        {"matcher": "*", "hooks": [{"type": "command", "command": CMD, "timeout": 630}]}
    ]
    assert "PermissionRequest" not in settings.get("hooks", {})  # input untouched


def test_install_is_idempotent_and_updates_in_place():
    once = plan_install({}, CMD, 630)
    assert plan_install(once, CMD, 630) == once
    updated = plan_install(once, "/opt/bgpt-host hook", 100)
    assert len(updated["hooks"]["PermissionRequest"]) == 1
    assert updated["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"] == 100


def test_uninstall_restores_original():
    original = {"theme": "dark"}
    assert plan_uninstall(plan_install(original, CMD, 630)) == original


def test_uninstall_keeps_foreign_permission_hooks():
    foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool"}]}
    s = plan_install({"hooks": {"PermissionRequest": [foreign]}}, CMD, 630)
    assert plan_uninstall(s) == {"hooks": {"PermissionRequest": [foreign]}}


def test_hook_installed():
    assert not hook_installed({})
    assert hook_installed(plan_install({}, CMD, 630))


def test_load_settings(tmp_path):
    assert load_settings(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    with pytest.raises(ValueError):
        load_settings(bad)


def test_run_change_writes_backup_after_confirm(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "dark"}))
    shown = []
    rc = run_change(path, lambda s: plan_install(s, CMD, 630), lambda diff: shown.append(diff) or True, lambda m: None)
    assert rc == 0 and "PermissionRequest" in shown[0]
    assert hook_installed(json.loads(path.read_text()))
    backups = list(tmp_path.glob("settings.json.bgpt-backup-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == {"theme": "dark"}


def test_run_change_declined_writes_nothing(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}")
    assert run_change(path, lambda s: plan_install(s, CMD, 630), lambda d: False, lambda m: None) == 0
    assert path.read_text() == "{}"


def test_run_change_noop(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(plan_install({}, CMD, 630)))
    msgs = []
    assert run_change(path, lambda s: plan_install(s, CMD, 630), lambda d: pytest.fail("asked"), msgs.append) == 0
    assert any("already" in m for m in msgs)


def test_run_change_broken_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{oops")
    assert run_change(path, lambda s: s, lambda d: True, lambda m: None) == 1
