"""
Tests for notifier.py.

The alerting path is the one place where a silent failure costs a real application window, so
these tests pin down three things: payload rendering is correct, missing credentials degrade to
``skipped`` (not a crash), and no code path can raise out of ``dispatch_transitions``.
"""

import json

import pytest

import notifier


def _transition(**overrides):
    base = {
        "id": "ba-speedbird",
        "airline": "British Airways",
        "program": "Speedbird Pilot Academy",
        "passport": "UK",
        "passport_label": "🇬🇧 UK",
        "rtw_scope": "UK Right to Work",
        "from": "CLOSED",
        "to": "OPEN",
        "trigger": "open",
        "first_run": False,
        "detected_at": "2026-02-12T08:00:00Z",
        "apply_url": "https://careers.ba.com/job/heathrow/speedbird-pilot-academy/22348/77265555216",
        "source_url": "https://careers.ba.com/speedbird-pilot-academy-preparation",
        "evidence": "Applications for 2027 have now opened.",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------


def test_plain_text_contains_apply_link_and_evidence():
    body = notifier.render_plain([_transition()])
    assert "British Airways" in body
    assert "CLOSED -> OPEN" in body
    assert "https://careers.ba.com/job/heathrow" in body
    assert "Applications for 2027 have now opened." in body


def test_markdown_v2_escapes_reserved_characters():
    escaped = notifier.escape_markdown_v2("A_B*C[D](E)~F`G>H#I+J-K=L|M{N}.O!P\\Q")
    for char in "_*[]()~`>#+-=|{}.!\\":
        assert "\\" + char in escaped


def test_telegram_markdown_is_escaped_but_keeps_the_link():
    payload = notifier.render_telegram_markdown([_transition(airline="Jet2.com", program="Jet2FlightPath (2026)")])
    # MarkdownV2 requires every reserved character in *text* to be escaped ...
    assert "\\(2026\\)" in payload
    assert "Jet2\\.com" in payload
    # ... while the link target itself is passed through verbatim (only ')' needs escaping).
    assert "[Apply now →](https://careers.ba.com/job/heathrow/speedbird-pilot-academy/22348/77265555216)" in payload


def test_telegram_markdown_header_is_bold_only_when_something_is_open():
    open_payload = notifier.render_telegram_markdown([_transition()])
    assert "*PILOT CADET ALERT*" in open_payload

    closed_payload = notifier.render_telegram_markdown([_transition(to="CLOSED", trigger="closed")])
    assert "PILOT CADET ALERT" not in closed_payload


def test_html_body_escapes_injected_markup():
    html = notifier.render_html([_transition(evidence="<script>alert(1)</script>")])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_subject_prioritises_open_transitions():
    subject = notifier.subject_for([_transition(), _transition(id="jet2-flightpath", airline="Jet2.com", to="CLOSED")])
    assert subject.startswith("🚨 APPLICATIONS OPEN")
    assert "British Airways" in subject


def test_empty_transition_list_renders_a_clear_message():
    assert "No pilot cadet status changes" in notifier.render_plain([])


# --------------------------------------------------------------------------------------
# Channel behaviour
# --------------------------------------------------------------------------------------


def test_missing_credentials_are_skipped_not_failed(monkeypatch):
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "EMAIL_API_KEY", "EMAIL_TO", "SMTP_HOST"):
        monkeypatch.delenv(key, raising=False)

    report = notifier.dispatch_transitions([_transition()], dry_run=False)
    by_channel = {result.channel: result for result in report.results}

    assert by_channel["telegram"].skipped and not by_channel["telegram"].ok
    assert by_channel["email"].skipped and not by_channel["email"].ok
    assert report.any_sent is False
    assert report.all_failed is False  # skipped is not failed


def test_dry_run_sends_nothing_and_succeeds(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("EMAIL_API_KEY", "re_fake")
    monkeypatch.setenv("EMAIL_TO", "pilot@example.com")
    monkeypatch.setenv("EMAIL_FROM", "monitor@example.com")

    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("dry-run must not perform network I/O")

    monkeypatch.setattr(notifier, "_post_json", explode)
    monkeypatch.setattr(notifier, "_resend_post", explode)

    report = notifier.dispatch_transitions([_transition()], dry_run=True)
    assert report.dry_run is True
    assert all(result.ok for result in report.results)


def test_markdown_rejection_falls_back_to_plain_text(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("EMAIL_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    calls = []

    def fake_post(url, payload, timeout=20.0):
        calls.append(payload)
        # Telegram rejects MarkdownV2, then accepts the plain-text retry.
        if payload.get("parse_mode") == "MarkdownV2":
            return {"status_code": 400, "body": {"ok": False, "description": "can't parse entities"}}
        return {"status_code": 200, "body": {"ok": True, "result": {"message_id": 1}}}

    monkeypatch.setattr(notifier, "_post_json", fake_post)
    result = notifier.send_telegram([_transition()], dry_run=False)

    assert result.ok is True
    assert len(calls) == 2
    assert calls[0]["parse_mode"] == "MarkdownV2"
    assert "parse_mode" not in calls[1]


def test_transient_telegram_failure_is_retried(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(notifier.time, "sleep", lambda *_: None)

    attempts = {"n": 0}

    def flaky_post(url, payload, timeout=20.0):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return {"status_code": 503, "body": {"ok": False}}
        return {"status_code": 200, "body": {"ok": True}}

    monkeypatch.setattr(notifier, "_post_json", flaky_post)
    result = notifier.send_telegram([_transition()], dry_run=False)

    assert result.ok is True
    assert result.attempts >= 2


def test_dispatch_never_raises_even_when_a_channel_explodes(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("channel is on fire")

    monkeypatch.setattr(notifier, "send_telegram", boom)
    monkeypatch.setattr(notifier, "send_email", boom)

    report = notifier.dispatch_transitions([_transition()], dry_run=False)
    assert len(report.results) == 2
    assert report.all_failed is True
    assert all("channel is on fire" in result.detail for result in report.results)


def test_self_test_message_is_sent_when_nothing_changed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    captured = {}
    monkeypatch.setattr(
        notifier,
        "send_telegram",
        lambda transitions, dry_run=False: (
            captured.update(transitions=transitions)
            or notifier.ChannelResult(channel="telegram", ok=True, detail="ok")
        ),
    )
    monkeypatch.setattr(
        notifier, "send_email", lambda transitions, dry_run=False: notifier.ChannelResult(channel="email", ok=True, detail="ok")
    )

    report = notifier.dispatch_transitions([], dry_run=False, include_test_message=True)
    assert report.any_sent
    assert captured["transitions"][0]["id"] == "self-test"


# --------------------------------------------------------------------------------------
# CLI plumbing
# --------------------------------------------------------------------------------------


def test_load_transitions_reads_monitor_output(tmp_path):
    path = tmp_path / "transitions.json"
    path.write_text(
        json.dumps({"schema_version": 1, "generated_at": "2026-02-12T08:00:00Z", "transitions": [_transition()]}),
        encoding="utf-8",
    )
    assert notifier.load_transitions(path)[0]["id"] == "ba-speedbird"


def test_load_transitions_is_resilient_to_missing_or_broken_files(tmp_path):
    assert notifier.load_transitions(tmp_path / "nope.json") == []

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert notifier.load_transitions(broken) == []


def test_dry_run_cli_exits_zero_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_DRY_RUN", "1")
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "EMAIL_TO"):
        monkeypatch.delenv(key, raising=False)

    path = tmp_path / "transitions.json"
    path.write_text(json.dumps({"transitions": [_transition()]}), encoding="utf-8")
    assert notifier.main(["--transitions", str(path), "--dry-run"]) == 0
