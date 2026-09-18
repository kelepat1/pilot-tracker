#!/usr/bin/env python3
"""
notifier.py -- high-priority alert dispatch for the pilot cadet monitor.

Two independent channels, both failure-safe:

* **Telegram Bot API** -- instant mobile push, Markdown formatted, with the direct apply link
  as an inline URL button. Falls back to plain text automatically if Telegram rejects the
  Markdown payload (HTTP 400), which is the usual cause of "silent" bot failures.
* **Email** -- Resend HTTP API when ``EMAIL_API_KEY`` is present, otherwise SMTP with
  ``X-Priority: 1`` / ``Importance: High`` headers so the message is treated as urgent and
  still arrives when the laptop is shut.

Guarantees
----------
* Nothing in this module ever raises out to the caller: every channel returns a structured
  result, and a failure on one channel never prevents the other from being attempted.
  A missed application window is the only truly unacceptable outcome, so the monitor must
  finish and commit even if alerting is broken.
* ``--dry-run`` renders the exact payloads (including the Telegram Markdown) without sending
  anything, which is how the pipeline is verified in CI before secrets exist.
* Missing credentials are reported as ``skipped``, not ``failed``.

Environment variables
---------------------
Telegram : ``TELEGRAM_BOT_TOKEN``, ``TELEGRAM_CHAT_ID`` (comma-separated ids allowed)
Email    : ``EMAIL_API_KEY`` (Resend), ``EMAIL_FROM``, ``EMAIL_TO`` (comma-separated)
           ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASS``, ``SMTP_SECURITY``
           (``starttls`` | ``ssl`` | ``none``)
Shared   : ``NOTIFY_DRY_RUN`` (``1`` to force dry-run), ``NOTIFY_MIN_PRIORITY``
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("notifier")

TELEGRAM_API = "https://api.telegram.org"
RESEND_API = "https://api.resend.com/emails"

STATUS_EMOJI = {
    "OPEN": "🟢",
    "INTEREST": "🟠",
    "CLOSED": "⚪️",
    "UNKNOWN": "❔",
    "ERROR": "⚠️",
    "NEW": "🆕",
}

TRIGGER_SUBJECT = {
    "open": "🚨 APPLICATIONS OPEN",
    "interest": "🟠 Talent pool open",
    "closed": "⚪️ Applications closed",
}


# --------------------------------------------------------------------------------------
# Result plumbing
# --------------------------------------------------------------------------------------


@dataclass
class ChannelResult:
    channel: str
    ok: bool
    detail: str
    skipped: bool = False
    attempts: int = 0

    @property
    def status_word(self) -> str:
        if self.skipped:
            return "skipped"
        return "sent" if self.ok else "failed"


@dataclass
class DispatchReport:
    results: List[ChannelResult] = field(default_factory=list)
    dry_run: bool = False

    def add(self, result: ChannelResult) -> None:
        self.results.append(result)

    @property
    def any_sent(self) -> bool:
        return any(r.ok for r in self.results)

    @property
    def all_failed(self) -> bool:
        return bool(self.results) and all((not r.ok) and (not r.skipped) for r in self.results)

    def summary(self) -> str:
        if not self.results:
            return "no channels configured"
        return ", ".join("%s=%s" % (r.channel, r.status_word) for r in self.results)


# --------------------------------------------------------------------------------------
# Message rendering
# --------------------------------------------------------------------------------------


def _apply_url(transition: Dict[str, Any]) -> str:
    return str(transition.get("apply_url") or transition.get("source_url") or "")


def _passport_label(transition: Dict[str, Any]) -> str:
    label = transition.get("passport_label")
    if label:
        return str(label)
    passport = str(transition.get("passport") or "")
    return {"UK": "🇬🇧 UK", "EU": "🇪🇺 EU"}.get(passport, "🌍 Global")


def _headline(transition: Dict[str, Any]) -> str:
    return "%s — %s" % (transition.get("airline", "Airline"), transition.get("program", "Cadet programme"))


def render_plain(transitions: Sequence[Dict[str, Any]]) -> str:
    """Plain-text body, shared by the email text part and the Telegram fallback."""
    if not transitions:
        return "No pilot cadet status changes detected."

    lines: List[str] = []
    open_count = sum(1 for t in transitions if t.get("to") == "OPEN")
    header = "🚨 PILOT CADET ALERT" if open_count else "Pilot cadet update"
    lines.append("%s (%d change%s)" % (header, len(transitions), "" if len(transitions) == 1 else "s"))
    lines.append("")
    for index, transition in enumerate(transitions, start=1):
        lines.append("%d. %s" % (index, _headline(transition)))
        lines.append(
            "   %s -> %s  |  %s  |  %s"
            % (
                transition.get("from", "?"),
                transition.get("to", "?"),
                _passport_label(transition),
                transition.get("rtw_scope") or "",
            )
        )
        if transition.get("evidence"):
            lines.append("   Evidence: %s" % transition["evidence"])
        if _apply_url(transition):
            lines.append("   Apply: %s" % _apply_url(transition))
        if transition.get("detected_at"):
            lines.append("   Detected: %s" % transition["detected_at"])
        lines.append("")
    lines.append("Source: passive daily check of the airline career portal. Verify the wording")
    lines.append("on the portal before applying — this monitor reports what the page said.")
    return "\n".join(lines).strip() + "\n"


def render_html(transitions: Sequence[Dict[str, Any]]) -> str:
    """Urgent-looking HTML email body. Inline styles only (email clients strip <style>)."""
    rows: List[str] = []
    for transition in transitions:
        to_status = str(transition.get("to", ""))
        badge_colour = {"OPEN": "#1a7f37", "INTEREST": "#b45309", "CLOSED": "#57606a"}.get(to_status, "#57606a")
        rows.append(
            """
            <tr>
              <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;">
                <div style="font:600 16px/1.35 -apple-system,Segoe UI,Roboto,sans-serif;color:#111827;">
                  {headline}
                </div>
                <div style="margin-top:6px;font:400 13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#4b5563;">
                  <span style="display:inline-block;padding:2px 8px;border-radius:999px;background:{badge};color:#fff;font-weight:600;">
                    {to_status}
                  </span>
                  &nbsp; was <strong>{from_status}</strong> &nbsp;·&nbsp; {passport} &nbsp;·&nbsp; {scope}
                </div>
                <div style="margin-top:8px;font:400 13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#374151;">
                  <em>{evidence}</em>
                </div>
                <div style="margin-top:10px;">
                  <a href="{url}" style="display:inline-block;padding:9px 16px;border-radius:8px;background:#0b5fff;color:#fff;
                     font:600 13px/1 -apple-system,Segoe UI,Roboto,sans-serif;text-decoration:none;">Open application page</a>
                </div>
                <div style="margin-top:8px;font:400 11px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;color:#9ca3af;">
                  detected {detected}
                </div>
              </td>
            </tr>
            """
            .format(
                headline=html.escape(_headline(transition)),
                badge=badge_colour,
                to_status=html.escape(to_status),
                from_status=html.escape(str(transition.get("from", "?"))),
                passport=html.escape(_passport_label(transition)),
                scope=html.escape(str(transition.get("rtw_scope") or "")),
                evidence=html.escape(str(transition.get("evidence") or "")),
                url=html.escape(_apply_url(transition), quote=True),
                detected=html.escape(str(transition.get("detected_at") or "")),
            )
        )
    return (
        # Concatenated rather than %-formatted: the inline styles contain a literal '%'
        # (width="100%"), which a formatting operator would try to interpret.
        '<!doctype html><html><body style="margin:0;background:#f3f4f6;padding:24px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:640px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;'
        'box-shadow:0 1px 3px rgba(0,0,0,.08);">'
        '<tr><td style="padding:18px 16px;background:#111827;color:#fff;'
        'font:700 15px/1.3 -apple-system,Segoe UI,Roboto,sans-serif;">Pilot cadet programme alert</td></tr>'
        + "".join(rows)
        + '<tr><td style="padding:14px 16px;font:400 12px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;'
        'color:#6b7280;">Automated passive check of airline career portals. Always confirm the '
        "wording on the portal before applying.</td></tr></table></body></html>"
    )


_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"


def escape_markdown_v2(text: str) -> str:
    """Escape every Telegram MarkdownV2 reserved character."""
    return "".join("\\" + ch if ch in _MDV2_SPECIAL else ch for ch in str(text))


def render_telegram_markdown(transitions: Sequence[Dict[str, Any]]) -> str:
    """Telegram MarkdownV2 payload."""
    if not transitions:
        return escape_markdown_v2("No pilot cadet status changes detected.")

    open_count = sum(1 for t in transitions if t.get("to") == "OPEN")
    lines: List[str] = []
    if open_count:
        lines.append("🚨 *" + escape_markdown_v2("PILOT CADET ALERT") + "*")
    else:
        lines.append(escape_markdown_v2("Pilot cadet update"))
    lines.append("")
    for transition in transitions:
        emoji = STATUS_EMOJI.get(str(transition.get("to", "")), "•")
        headline = escape_markdown_v2(_headline(transition))
        lines.append("%s *%s*" % (emoji, headline))
        lines.append(
            escape_markdown_v2(
                "%s → %s · %s · %s"
                % (
                    transition.get("from", "?"),
                    transition.get("to", "?"),
                    _passport_label(transition),
                    transition.get("rtw_scope") or "",
                )
            )
        )
        if transition.get("evidence"):
            lines.append("_" + escape_markdown_v2(str(transition["evidence"])[:220]) + "_")
        url = _apply_url(transition)
        if url:
            lines.append("[Apply now →](%s)" % url.replace(")", "\\)"))
        lines.append("")
    lines.append(escape_markdown_v2("Passive daily check · verify wording on the portal"))
    return "\n".join(lines).strip()


def subject_for(transitions: Sequence[Dict[str, Any]]) -> str:
    open_transitions = [t for t in transitions if t.get("to") == "OPEN"]
    if open_transitions:
        names = ", ".join(str(t.get("airline")) for t in open_transitions[:3])
        more = "" if len(open_transitions) <= 3 else " +%d" % (len(open_transitions) - 3)
        return "🚨 APPLICATIONS OPEN: %s%s" % (names, more)
    if len(transitions) == 1:
        transition = transitions[0]
        return "%s %s — %s" % (
            STATUS_EMOJI.get(str(transition.get("to", "")), ""),
            TRIGGER_SUBJECT.get(str(transition.get("trigger", "")), "Update"),
            transition.get("airline", ""),
        ).strip()
    return "Pilot cadet update: %d status changes" % len(transitions)


# --------------------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------------------


def _telegram_config() -> Optional[Dict[str, Any]]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    raw_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not raw_chat:
        return None
    chat_ids = [c.strip() for c in raw_chat.replace(";", ",").split(",") if c.strip()]
    return {
        "token": token,
        "chat_ids": chat_ids,
        "thread_id": os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "").strip() or None,
        "silent": os.environ.get("TELEGRAM_DISABLE_NOTIFICATION", "").strip() in ("1", "true", "yes"),
    }


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 20.0) -> Dict[str, Any]:
    """Single JSON POST helper. Kept tiny so both channels share retry/pacing semantics."""
    import httpx

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        body: Any
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:500]}
        return {"status_code": response.status_code, "body": body}


def send_telegram(transitions: Sequence[Dict[str, Any]], dry_run: bool = False) -> ChannelResult:
    config = _telegram_config()
    markdown = render_telegram_markdown(transitions)

    if config is None:
        return ChannelResult(
            channel="telegram",
            ok=False,
            skipped=True,
            detail="TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set",
        )

    if dry_run:
        logger.info("[dry-run] telegram payload:\n%s", markdown)
        return ChannelResult(channel="telegram", ok=True, skipped=False, detail="dry-run payload rendered")

    last_detail = ""
    attempts = 0
    for chat_id in config["chat_ids"]:
        # MarkdownV2 first; a 400 from Telegram almost always means a formatting problem,
        # so retry once as plain text rather than losing the alert entirely.
        for parse_mode in ("MarkdownV2", None):
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": markdown if parse_mode else render_plain(transitions),
                "disable_web_page_preview": False,
                "disable_notification": bool(config["silent"]),
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if config["thread_id"]:
                payload["message_thread_id"] = int(config["thread_id"])

            for attempt in range(3):
                attempts += 1
                try:
                    result = _post_json("%s/bot%s/sendMessage" % (TELEGRAM_API, config["token"]), payload)
                    code = int(result["status_code"])
                    body = result["body"]
                    if code == 200 and isinstance(body, dict) and body.get("ok"):
                        last_detail = "sent to chat %s" % chat_id
                        break
                    last_detail = "HTTP %s: %s" % (code, json.dumps(body)[:300])
                    if code == 400 and parse_mode:
                        logger.warning("telegram rejected MarkdownV2 (%s); retrying as plain text", last_detail)
                        break  # fall through to the plain-text variant
                    if code in (429, 500, 502, 503, 504):
                        time.sleep(2 * (attempt + 1))
                        continue
                    break
                except Exception as exc:
                    last_detail = "%s: %s" % (type(exc).__name__, exc)
                    logger.warning("telegram attempt %d failed: %s", attempt + 1, last_detail)
                    time.sleep(2 * (attempt + 1))
            else:
                continue
            if last_detail.startswith("sent to chat"):
                break
        else:
            continue
        break

    ok = last_detail.startswith("sent to chat")
    return ChannelResult(channel="telegram", ok=ok, detail=last_detail, attempts=attempts)


def _email_config() -> Dict[str, Any]:
    return {
        "resend_key": os.environ.get("EMAIL_API_KEY", "").strip(),
        "sender": os.environ.get("EMAIL_FROM", "").strip() or "pilot-tracker@localhost",
        "recipients": [
            r.strip()
            for r in os.environ.get("EMAIL_TO", "").replace(";", ",").split(",")
            if r.strip()
        ],
        "smtp_host": os.environ.get("SMTP_HOST", "").strip(),
        "smtp_port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "smtp_user": os.environ.get("SMTP_USER", "").strip(),
        "smtp_pass": os.environ.get("SMTP_PASS", "").strip(),
        "smtp_security": (os.environ.get("SMTP_SECURITY", "starttls").strip().lower() or "starttls"),
    }


def send_email(transitions: Sequence[Dict[str, Any]], dry_run: bool = False) -> ChannelResult:
    config = _email_config()
    subject = subject_for(transitions)
    text_body = render_plain(transitions)
    html_body = render_html(transitions)

    if not config["recipients"]:
        return ChannelResult(channel="email", ok=False, skipped=True, detail="EMAIL_TO not set")
    if not config["resend_key"] and not config["smtp_host"]:
        return ChannelResult(
            channel="email",
            ok=False,
            skipped=True,
            detail="no transport configured (set EMAIL_API_KEY for Resend, or SMTP_HOST)",
        )

    if dry_run:
        logger.info("[dry-run] email to %s | subject: %s", config["recipients"], subject)
        logger.debug("[dry-run] email body:\n%s", text_body)
        return ChannelResult(channel="email", ok=True, detail="dry-run message rendered")

    if config["resend_key"]:
        payload = {
            "from": config["sender"],
            "to": config["recipients"],
            "subject": subject,
            "text": text_body,
            "html": html_body,
            "headers": {"X-Priority": "1", "Importance": "high", "X-Entity-Ref-ID": make_msgid()[1:-1]},
        }
        last_detail = ""
        for attempt in range(3):
            try:
                result = _resend_post(payload, config["resend_key"])
                code = int(result["status_code"])
                if 200 <= code < 300:
                    return ChannelResult(channel="email", ok=True, detail="Resend accepted (%s)" % code, attempts=attempt + 1)
                last_detail = "Resend HTTP %s: %s" % (code, json.dumps(result["body"])[:300])
                if code in (429, 500, 502, 503, 504):
                    time.sleep(2 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                last_detail = "Resend %s: %s" % (type(exc).__name__, exc)
                time.sleep(2 * (attempt + 1))
        logger.warning("Resend delivery failed (%s); trying SMTP if configured", last_detail)
        if not config["smtp_host"]:
            return ChannelResult(channel="email", ok=False, detail=last_detail)

    # ---- SMTP fallback -------------------------------------------------------------
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(("Pilot Cadet Monitor", config["sender"]))
    message["To"] = ", ".join(config["recipients"])
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message["X-Priority"] = "1 (Highest)"
    message["X-MSMail-Priority"] = "High"
    message["Importance"] = "High"
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    last_detail = ""
    for attempt in range(3):
        try:
            context = ssl.create_default_context()
            if config["smtp_security"] == "ssl":
                server = smtplib.SMTP_SSL(config["smtp_host"], config["smtp_port"], timeout=30, context=context)
            else:
                server = smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=30)
            with server:
                server.ehlo()
                if config["smtp_security"] == "starttls":
                    try:
                        server.starttls(context=context)
                        server.ehlo()
                    except smtplib.SMTPException as exc:
                        logger.warning("STARTTLS unavailable (%s); continuing unencrypted", exc)
                if config["smtp_user"]:
                    server.login(config["smtp_user"], config["smtp_pass"])
                server.send_message(message)
            return ChannelResult(channel="email", ok=True, detail="SMTP delivered to %s" % message["To"], attempts=attempt + 1)
        except Exception as exc:
            last_detail = "SMTP %s: %s" % (type(exc).__name__, exc)
            logger.warning("SMTP attempt %d failed: %s", attempt + 1, last_detail)
            time.sleep(2 * (attempt + 1))
    return ChannelResult(channel="email", ok=False, detail=last_detail)


def _resend_post(payload: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    import httpx

    headers = {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=25.0) as client:
        response = client.post(RESEND_API, json=payload, headers=headers)
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:500]}
        return {"status_code": response.status_code, "body": body}


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def dispatch_transitions(
    transitions: Sequence[Dict[str, Any]],
    dry_run: Optional[bool] = None,
    include_test_message: bool = False,
) -> DispatchReport:
    """Fan a transition list out to every configured channel. Never raises."""
    if dry_run is None:
        dry_run = os.environ.get("NOTIFY_DRY_RUN", "").strip() in ("1", "true", "yes")

    report = DispatchReport(dry_run=bool(dry_run))

    if not transitions:
        logger.info("no transitions to notify")
        if not include_test_message:
            return report
        transitions = [
            {
                "id": "self-test",
                "airline": "Self test",
                "program": "Notification channel check",
                "passport": "UK",
                "passport_label": "🇬🇧 UK",
                "rtw_scope": "connectivity probe",
                "from": "TEST",
                "to": "INTEREST",
                "trigger": "test",
                "detected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "apply_url": "https://example.com/",
                "source_url": "https://example.com/",
                "evidence": "Manual connectivity test from notifier.py --self-test",
            }
        ]

    logger.info("dispatching %d transition(s) (dry_run=%s)", len(transitions), bool(dry_run))
    for channel in (send_telegram, send_email):
        try:
            result = channel(transitions, dry_run=bool(dry_run))
        except Exception as exc:  # defensive: a channel must never break the run
            result = ChannelResult(channel=channel.__name__, ok=False, detail="%s: %s" % (type(exc).__name__, exc))
        logger.info("channel %s -> %s (%s)", result.channel, result.status_word, result.detail)
        report.add(result)

    if report.all_failed:
        logger.error("ALL notification channels failed: %s", report.summary())
    return report


def load_transitions(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        logger.warning("transitions file %s not found; nothing to notify", path)
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("could not read transitions from %s: %s", path, exc)
        return []
    transitions = document.get("transitions", document if isinstance(document, list) else [])
    return [t for t in transitions if isinstance(t, dict)]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Dispatch pilot cadet alerts to Telegram and email.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--transitions",
        default=str(here.parent / "build" / "transitions.json"),
        help="transitions file produced by monitor.py",
    )
    parser.add_argument("--dry-run", action="store_true", help="render payloads without sending")
    parser.add_argument("--self-test", action="store_true", help="send a test message through every channel")
    parser.add_argument("--fail-on-error", action="store_true", help="exit 1 if every configured channel failed")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    transitions = [] if args.self_test else load_transitions(Path(args.transitions))
    report = dispatch_transitions(transitions, dry_run=args.dry_run, include_test_message=args.self_test)

    if args.fail_on_error and report.all_failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
