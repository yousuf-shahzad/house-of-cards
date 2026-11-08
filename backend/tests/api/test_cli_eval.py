"""I-API v3 (d): `hoc eval` in hoc.cli replays the recorded held-out predictions offline (no network, no Gemini)."""

from __future__ import annotations

import json

import pytest

from hoc.cli import main


def test_hoc_eval_replay_writes_both_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOC_OFFLINE", "1")  # replay must not need the network
    md, out = tmp_path / "EVAL.md", tmp_path / "results.json"
    assert main(["eval", "--replay", "--out-md", str(md), "--out-json", str(out)]) == 0
    assert md.read_text(encoding="utf-8").strip()
    results = json.loads(out.read_text(encoding="utf-8"))
    assert results  # the harness's own tests check the numbers; here only the CLI wiring
    assert "Micro Precision" in capsys.readouterr().out


def test_hoc_eval_help_names_the_modes(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["eval", "--help"])
    assert exit_info.value.code == 0
    text = capsys.readouterr().out
    assert "--replay" in text and "--live" in text
