#!/usr/bin/env python3
"""
monitor.py -- passive daily status monitor for fully funded airline pilot cadet programmes.

What it does
------------
1. Loads the programme catalogue from ``targets.json`` (URLs, selectors, passport tags, rules).
2. Fetches each career portal with a fast-path ``httpx`` request. If the page is JavaScript
   heavy (Workday / SuccessFactors / Taleo / Cloudflare interstitial) it escalates to a
   headless Chromium via Playwright.
3. Extracts the *primary content container* for the programme, scrubs volatile noise
   (timestamps, nonces, session ids, copyright years) and takes a persistent SHA-256 hash
   of the result. The hash - not the raw page - is what is used for change detection, which
   is what keeps the check free of false positives caused by tracking tokens.
4. Classifies the state as ``OPEN`` / ``INTEREST`` / ``CLOSED`` (or ``UNKNOWN`` / ``ERROR``)
   using an ordered, first-match-wins rule engine. Ordering is explicit in ``targets.json``
   so "not yet open" can be matched *before* "open" via negative lookahead.
5. Merges the result with the previous ``status.json`` so that ``changed_at`` and
   ``consecutive_failures`` survive across runs, then writes:
      * ``status.json``            -- the public, cloud-synced state file (committed by CI)
      * ``build/transitions.json`` -- the transitions to alert on (consumed by notifier.py)

Design notes
------------
* Zero dependencies on a local machine: this file is executed by GitHub Actions only.
* Failure isolation: one broken portal never aborts the run. A portal that cannot be read
  keeps its last known status and increments ``consecutive_failures``.
* ``--offline --fixtures-dir`` replays captured HTML so the whole pipeline can be verified
  without touching the network.
* Python 3.11+ is used in CI; the code deliberately also parses under 3.9 so it can be
  smoke tested anywhere.

Exit codes: 0 success (per-program errors tolerated), 1 fatal (config/output failure or
``--fail-on-error`` with at least one errored program).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------

SCHEMA_VERSION = 1

STATUS_OPEN = "OPEN"
STATUS_INTEREST = "INTEREST"
STATUS_CLOSED = "CLOSED"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_ERROR = "ERROR"

ACTIONABLE_STATUSES = (STATUS_OPEN, STATUS_INTEREST)
VALID_STATUSES = (STATUS_OPEN, STATUS_INTEREST, STATUS_CLOSED, STATUS_UNKNOWN, STATUS_ERROR)

# Rules run in *phases*, not in raw list order. This removes a trap that is easy to fall into
# when editing the catalogue: a negation such as "not currently open" contains the word "open",
# and a job-alert interest route on the same page must outrank the closing sentence that sits
# next to it. Phase order is therefore part of the engine, and only rules inside one phase are
# evaluated first-match-wins.
PHASE_ORDER: Dict[str, int] = {
    "guard": 0,  # bot walls / maintenance pages -> UNKNOWN
    "negation": 1,  # "not currently open": must beat the OPEN phase
    "open": 2,
    "interest": 3,  # must beat "closed": a talent-pool route is actionable
    "closed": 4,
    "fallback": 5,
}

DEFAULT_PHASE_BY_STATUS = {
    STATUS_UNKNOWN: "guard",
    STATUS_OPEN: "open",
    STATUS_INTEREST: "interest",
    STATUS_CLOSED: "closed",
    STATUS_ERROR: "closed",
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 PilotCadetMonitor/1.0 "
    "(+https://github.com/; passive daily status check)"
)

# Words that only ever appear on an interstitial / blocked response.
# "pardon our interruption" and the bot-accusation wording are Imperva/Distil, which is what
# www.aerlingus.com serves to any non-browser client (observed 2026-09-18).
BLOCK_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
    "request unsuccessful. incapsula",
    "access denied |",
    "px-captcha",
    "please verify you are a human",
    "pardon our interruption",
    "made us think you were a bot",
    "you've disabled javascript",
)

# Substrings that indicate an unshelled SPA (JS must run before content exists).
JS_SHELL_MARKERS = (
    "you need to enable javascript to run this app",
    "please enable javascript to view",
    "enable javascript to continue",
    "noscript",
)

logger = logging.getLogger("monitor")


class ConfigError(RuntimeError):
    """Raised when targets.json is malformed. Fatal: we never guess at selectors."""


class FetchError(RuntimeError):
    """Raised when a page could not be retrieved or was blocked.

    ``status_code`` is carried so a programme can map a specific HTTP status onto a real
    status (see ``http_status_overrides``): TUI's MPL page was deleted by the airline, and a
    404 there genuinely means "no intake page published", not "the scraper is broken".
    """

    def __init__(self, message: str, status_code: Optional[int] = None, url: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class ExtractionError(RuntimeError):
    """Raised when a retrieved page yielded no usable content container."""


# --------------------------------------------------------------------------------------
# Text hygiene: normalisation, scrubbing, hashing
# --------------------------------------------------------------------------------------

# Ordered volatile-noise scrubbers. Each replaces a *transient* token that would
# otherwise flip the content hash on every single run.
VOLATILE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # ISO-8601 / RFC-1123 timestamps, with or without a time component.
    (
        r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"
        r"(?:Z|[+-]\d{2}:?\d{2})?\b",
        "<TS>",
    ),
    (
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,? \d{1,2} "
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4} "
        r"\d{2}:\d{2}(?::\d{2})?(?: [A-Z]{2,4})?\b",
        "<TS>",
    ),
    # "Page last updated: 12 February 2026 at 09:41" and friends.
    (
        r"(?i)\b(?:page\s+)?(?:last\s+|recently\s+)?(?:updated|modified|refreshed|generated|"
        r"reviewed|checked|published|printed|as\s+of)\b[^.\n|<>]{0,60}",
        "<VOLATILE>",
    ),
    # Tracking / anti-CSRF / session material in text or in inlined URLs.
    (
        r"(?i)\b(?:nonce|csrf(?:token)?|xsrf|authenticity_token|jsessionid|sessionid|session_id|"
        r"phpsessid|sid|_ga|_gl|utm_[a-z]+|gclid|fbclid|msclkid|mc_[a-z]+id|"
        r"piwik_campaign|hsa_[a-z]+)=[^\s&\"'<>]{1,200}",
        "<TOKEN>",
    ),
    # Long opaque hex / base64 blobs (asset fingerprints, build hashes).
    (r"\b[A-Fa-f0-9]{16,}\b", "<TOKEN>"),
    (r"\b[A-Za-z0-9+/]{40,}={0,2}\b", "<TOKEN>"),
    # Cache-busting query strings.
    (r"\?[^\s\"'<>]*(?:v|ver|version|cb|cachebuster|ts)=\d{6,}[^\s\"'<>]*", "?<BUST>"),
    # Copyright / legal year stamps.
    (r"(?i)©\s*\d{4}(?:\s*[-–]\s*\d{4})?", "<YEAR>"),
    (r"(?i)\bcopyright\b[^.\n|<>]{0,80}\b(?:19|20)\d{2}\b[^.\n|<>]{0,40}", "<YEAR>"),
    # Relative "3 minutes ago" counters.
    (r"(?i)\b\d+\s+(?:second|minute|hour|day|week|month)s?\s+ago\b", "<AGO>"),
    # Open-positions counters rendered by job boards ("1,284 jobs").
    (r"(?i)\b[\d.,]{1,9}\s+(?:jobs?|positions?|vacanc(?:y|ies)|results?|matches)\b", "<COUNT>"),
    # Cookie-banner / consent churn.
    (r"(?i)\bcookie(?:s)?\b[^.\n|<>]{0,120}", "<COOKIE>"),
)

_COMPILED_VOLATILE: Tuple[Tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), repl) for pattern, repl in VOLATILE_PATTERNS
)

_WHITESPACE_RE = re.compile(r"[ \t\u00a0\u2007\u202f]+")
_BLANKLINE_RE = re.compile(r"\n{3,}")


def normalize_text(raw: str) -> str:
    """Collapse whitespace and drop blank-line runs so cosmetic churn is invisible."""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANKLINE_RE.sub("\n\n", text)
    return text.strip()


def scrub_volatile(text: str) -> str:
    """Replace transient tokens (timestamps, nonces, cache busters) with placeholders."""
    scrubbed = text
    for pattern, replacement in _COMPILED_VOLATILE:
        scrubbed = pattern.sub(replacement, scrubbed)
    return normalize_text(scrubbed)


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strip_url_noise(url: str) -> str:
    """Remove query/fragment so tracked links hash identically across runs."""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))


# --------------------------------------------------------------------------------------
# Rule engine
# --------------------------------------------------------------------------------------


@dataclass
class Rule:
    """One ordered classification rule.

    ``pattern``      : regex tested against the classification text (case-insensitive).
    ``require_all``  : every regex must match as well (compound rules).
    ``unless``       : if any of these match, the rule is disqualified.
    ``probe``        : DOM element-count probe, e.g. "2+ cadet listings exist".
    ``status``       : status emitted when the rule fires.
    """

    index: int
    status: str
    phase: str = "closed"
    pattern: Optional[re.Pattern] = None
    require_all: List[re.Pattern] = field(default_factory=list)
    unless: List[re.Pattern] = field(default_factory=list)
    probe: Optional[Dict[str, Any]] = None
    note: str = ""
    source: str = ""

    def matches(self, ctx: "RuleContext") -> Optional[Dict[str, Any]]:
        if self.probe:
            return self._match_probe(ctx)
        if self.pattern is None:
            return None
        if self.unless and any(ctx.any_segment_matches(p) for p in self.unless):
            return None
        if not all(ctx.any_segment_matches(p) for p in self.require_all):
            return None
        found = ctx.match_in_segments(self.pattern)
        if not found:
            return None
        hit, offset = found
        return {
            "matched": hit.group(0).strip(),
            "span": [offset + hit.start(), offset + hit.end()],
            "note": self.note,
            "source": "text",
        }

    def _match_probe(self, ctx: "RuleContext") -> Optional[Dict[str, Any]]:
        assert self.probe is not None
        selector = str(self.probe.get("selector", ""))
        min_count = int(self.probe.get("min_count", 1))
        text_match = self.probe.get("text_match")
        count = 0
        for element in ctx.select(selector):
            if text_match:
                haystack = " ".join(
                    [element.get_text(" ", strip=True)] + [element.get(k, "") for k in ("aria-label", "title", "href")]
                )
                if not re.search(str(text_match), haystack, re.IGNORECASE):
                    continue
            count += 1
        ctx.probe_counts[self.index] = count
        if count >= min_count:
            return {
                "matched": "probe=%s count=%d (min %d)" % (selector, count, min_count),
                "span": None,
                "note": self.note,
                "source": "probe",
            }
        return None


LINKS_SEPARATOR = "\n--- LINKS ---\n"


@dataclass
class RuleContext:
    """Everything a rule is allowed to look at.

    ``classification_text`` is the joined view used for reporting, while ``segments`` is what
    rules actually match against: the content container and the link-label list *separately*.
    Matching the joined string would let a pattern such as "apply now within 160 characters of
    a cadet keyword" satisfy its two halves on either side of the boundary - a proximity test
    that never actually saw the two strings near each other.
    """

    classification_text: str
    container_text: str
    select: Any  # callable(selector) -> list of soup elements
    segments: List[Tuple[str, int]] = field(default_factory=list)
    probe_counts: Dict[int, int] = field(default_factory=dict)

    def match_in_segments(self, pattern: re.Pattern) -> Optional[Tuple[Any, int]]:
        """Search each segment, returning the match plus its offset in the joined text."""
        for text, offset in (self.segments or [(self.classification_text, 0)]):
            hit = pattern.search(text)
            if hit:
                return hit, offset
        return None

    def any_segment_matches(self, pattern: re.Pattern) -> bool:
        return self.match_in_segments(pattern) is not None


@dataclass
class ProgramTarget:
    id: str
    airline: str
    program: str
    passport: str
    passport_label: str
    rtw_scope: str
    primary_url: str
    apply_url: str
    fallback_urls: List[str]
    engine: str
    auto_escalate: bool
    wait_for_selector: Optional[str]
    wait_until: str
    post_load_wait_ms: int
    content_selectors: List[str]
    apply_link_selectors: List[str]
    min_text_chars: int
    fallback_status: str
    fallback_note: str
    rules: List[Rule]
    timeout_s: float
    notes: str
    http_status_overrides: Dict[str, str] = field(default_factory=dict)
    http_status_override_note: str = ""
    watch_urls: List[str] = field(default_factory=list)
    secondary_text_urls: List[str] = field(default_factory=list)
    prefer_configured_apply_url: bool = False

    @property
    def urls(self) -> List[str]:
        seen: List[str] = []
        for url in [self.primary_url] + list(self.fallback_urls):
            if url and url not in seen:
                seen.append(url)
        return seen


@dataclass
class TargetsConfig:
    user_agent: str
    polite_delay_s: float
    max_retries: int
    retry_backoff_s: float
    request_timeout_s: float
    programs: List[ProgramTarget]
    raw: Dict[str, Any]


def _compile_regex(pattern: str, where: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.IGNORECASE | re.DOTALL)
    except re.error as exc:  # pragma: no cover - config authoring error
        raise ConfigError("invalid regex in %s: %r (%s)" % (where, pattern, exc)) from exc


def _parse_rule(raw: Dict[str, Any], index: int, where: str) -> Rule:
    status = str(raw.get("status", "")).upper()
    if status not in VALID_STATUSES:
        raise ConfigError("%s rule[%d]: status must be one of %s" % (where, index, VALID_STATUSES))
    phase = str(raw.get("phase") or DEFAULT_PHASE_BY_STATUS[status]).lower()
    if phase not in PHASE_ORDER:
        raise ConfigError(
            "%s rule[%d]: phase must be one of %s" % (where, index, sorted(PHASE_ORDER, key=PHASE_ORDER.get))
        )
    pattern = raw.get("match")
    require_all = raw.get("require_all") or []
    unless = raw.get("unless") or []
    probe = raw.get("probe")
    if not pattern and not probe:
        raise ConfigError("%s rule[%d]: needs either 'match' or 'probe'" % (where, index))
    if isinstance(require_all, str):
        require_all = [require_all]
    if isinstance(unless, str):
        unless = [unless]
    note = str(raw.get("note", ""))
    return Rule(
        index=index,
        status=status,
        phase=phase,
        pattern=_compile_regex(str(pattern), "%s rule[%d]" % (where, index)) if pattern else None,
        require_all=[
            _compile_regex(str(p), "%s rule[%d].require_all" % (where, index)) for p in require_all
        ],
        unless=[_compile_regex(str(p), "%s rule[%d].unless" % (where, index)) for p in unless],
        probe=probe if isinstance(probe, dict) else None,
        note=note,
        source="rules[%d]" % index,
    )


def load_targets(path: Path) -> TargetsConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError("targets file not found: %s" % path) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError("targets file is not valid JSON: %s (%s)" % (path, exc)) from exc

    defaults = raw.get("defaults", {}) or {}
    rule_sets = raw.get("rule_sets", {}) or {}
    if not isinstance(rule_sets, dict):
        raise ConfigError("'rule_sets' must be an object of name -> [rule, ...]")
    programs_raw = raw.get("programs")
    if not isinstance(programs_raw, list) or not programs_raw:
        raise ConfigError("targets file must contain a non-empty 'programs' array")

    programs: List[ProgramTarget] = []
    seen_ids = set()
    for entry in programs_raw:
        where = "program[%s]" % entry.get("id", "?")
        pid = str(entry.get("id", "")).strip()
        if not pid:
            raise ConfigError("%s: missing 'id'" % where)
        if pid in seen_ids:
            raise ConfigError("%s: duplicate id %r" % (where, pid))
        seen_ids.add(pid)

        merged = dict(defaults)
        merged.update(entry)

        # Effective rule order = shared rule sets in the order listed, then the programme's
        # own rules. Order is semantic: the first matching rule wins, so shared negations
        # ("not currently open") must be listed ahead of shared affirmations.
        rule_names = merged.get("rule_sets") or []
        if isinstance(rule_names, str):
            rule_names = [rule_names]
        rules_raw: List[Any] = []
        for name in rule_names:
            if name not in rule_sets:
                raise ConfigError("%s: unknown rule set %r (available: %s)" % (where, name, sorted(rule_sets)))
            shared = rule_sets[name]
            if not isinstance(shared, list):
                raise ConfigError("rule set %r must be an array" % name)
            rules_raw.extend(shared)
        rules_raw.extend(merged.get("rules") or [])

        if not rules_raw:
            raise ConfigError("%s: needs a non-empty 'rules' array (or at least one rule set)" % where)
        # Parse (which validates each rule) and then order by phase. `sorted` is stable, so
        # the authored order survives inside each phase.
        parsed = [_parse_rule(raw_rule, index, where) for index, raw_rule in enumerate(rules_raw)]
        rules = sorted(parsed, key=lambda rule: PHASE_ORDER[rule.phase])
        for index, rule in enumerate(rules):
            rule.index = index
            rule.source = "rules[%d]" % index

        content_selectors = merged.get("content_selectors") or ["main", "article", "body"]
        if isinstance(content_selectors, str):
            content_selectors = [content_selectors]
        apply_link_selectors = merged.get("apply_link_selectors") or ["a"]
        if isinstance(apply_link_selectors, str):
            apply_link_selectors = [apply_link_selectors]

        engine = str(merged.get("engine", "static")).lower()
        if engine not in ("static", "playwright"):
            raise ConfigError("%s: engine must be 'static' or 'playwright'" % where)

        fallback_status = str(merged.get("fallback_status", STATUS_UNKNOWN)).upper()
        if fallback_status not in VALID_STATUSES:
            raise ConfigError("%s: fallback_status must be one of %s" % (where, VALID_STATUSES))

        overrides_raw = merged.get("http_status_overrides") or {}
        if not isinstance(overrides_raw, dict):
            raise ConfigError("%s: http_status_overrides must be an object of \"404\": \"CLOSED\"" % where)
        overrides: Dict[str, str] = {}
        for code, status in overrides_raw.items():
            status_upper = str(status).upper()
            if status_upper not in VALID_STATUSES:
                raise ConfigError("%s: http_status_overrides[%s] must be one of %s" % (where, code, VALID_STATUSES))
            overrides[str(code)] = status_upper

        primary_url = str(merged.get("primary_url", "")).strip()
        if not primary_url.startswith(("http://", "https://")):
            raise ConfigError("%s: primary_url must be an absolute http(s) URL" % where)

        programs.append(
            ProgramTarget(
                id=pid,
                airline=str(merged.get("airline", pid)),
                program=str(merged.get("program", "")),
                passport=str(merged.get("passport", "Global")),
                passport_label=str(merged.get("passport_label", "")),
                rtw_scope=str(merged.get("rtw_scope", "")),
                primary_url=primary_url,
                apply_url=str(merged.get("apply_url") or primary_url),
                fallback_urls=[str(u) for u in (merged.get("fallback_urls") or [])],
                engine=engine,
                auto_escalate=bool(merged.get("auto_escalate", True)),
                wait_for_selector=merged.get("wait_for_selector") or None,
                wait_until=str(merged.get("wait_until", "domcontentloaded")),
                post_load_wait_ms=int(merged.get("post_load_wait_ms", 1500)),
                content_selectors=[str(s) for s in content_selectors],
                apply_link_selectors=[str(s) for s in apply_link_selectors],
                min_text_chars=int(merged.get("min_text_chars", defaults.get("min_text_chars", 200))),
                fallback_status=fallback_status,
                fallback_note=str(merged.get("fallback_note", "")),
                rules=rules,
                timeout_s=float(merged.get("timeout_s", defaults.get("timeout_s", 30))),
                notes=str(merged.get("notes", "")),
                http_status_overrides=overrides,
                http_status_override_note=str(merged.get("http_status_override_note", "")),
                watch_urls=[str(u) for u in (merged.get("watch_urls") or [])],
                secondary_text_urls=[str(u) for u in (merged.get("secondary_text_urls") or [])],
                prefer_configured_apply_url=bool(merged.get("prefer_configured_apply_url", False)),
            )
        )

    return TargetsConfig(
        user_agent=str(raw.get("user_agent", DEFAULT_USER_AGENT)),
        polite_delay_s=float(raw.get("polite_delay_s", 2.0)),
        max_retries=int(raw.get("max_retries", 3)),
        retry_backoff_s=float(raw.get("retry_backoff_s", 3.0)),
        request_timeout_s=float(raw.get("request_timeout_s", 30.0)),
        programs=programs,
        raw=raw,
    )


# --------------------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------------------


@dataclass
class FetchResult:
    html: str
    final_url: str
    http_status: Optional[int]
    engine: str
    elapsed_ms: int
    blocked: bool = False


def _looks_blocked(html: str) -> bool:
    lowered = html[:20000].lower()
    return any(marker in lowered for marker in BLOCK_MARKERS)


def _looks_like_shell(html: str) -> bool:
    """True only when the document is a genuine "JavaScript required" placeholder.

    A bare <noscript> tag is NOT evidence: Wizz Air's server-rendered SuccessFactors page
    contains one and was escalated to Chromium unnecessarily. Only the *message inside*
    <noscript> counts.
    """
    lowered = html.lower()
    for marker in JS_SHELL_MARKERS:
        if marker == "noscript":
            continue
        if marker in lowered:
            return True
    for block in re.findall(r"<noscript[^>]*>(.*?)</noscript>", lowered, re.DOTALL)[:3]:
        if "enable javascript" in block or "javascript is disabled" in block:
            return True
    return False


def _is_tls_failure(exc: Exception) -> bool:
    """Detect a TLS/protocol-version refusal so it can be retried with Chromium's TLS stack.

    jet2careers.com refuses the older TLS stack of some Python builds outright
    ("TLSV1_ALERT_PROTOCOL_VERSION") even though the page is plain, unrendered HTML - so
    treating this as a hard failure would lose the status check for a whole programme.
    """
    text = "%s %s" % (type(exc).__name__, exc)
    return bool(re.search(r"(?i)\b(ssl|tls|certificate|handshake|alert protocol version)\b", text))


def fetch_static(url: str, config: TargetsConfig) -> FetchResult:
    """Fast path: one plain HTTP GET, no browser."""
    import httpx

    headers = {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9,hu;q=0.8,fr;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    started = time.monotonic()
    with httpx.Client(
        follow_redirects=True,
        timeout=config.request_timeout_s,
        headers=headers,
        trust_env=True,
    ) as client:
        response = client.get(url)
        elapsed = int((time.monotonic() - started) * 1000)
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            raise FetchError(
                "HTTP %s for %s" % (response.status_code, url),
                status_code=response.status_code,
                url=str(response.url),
            )
        if "html" not in content_type and "xml" not in content_type and content_type:
            raise FetchError("unexpected content-type %r for %s" % (content_type, url))
        html = response.text
        return FetchResult(
            html=html,
            final_url=str(response.url),
            http_status=response.status_code,
            engine="static",
            elapsed_ms=elapsed,
            blocked=_looks_blocked(html),
        )


def fetch_playwright(target: ProgramTarget, config: TargetsConfig) -> FetchResult:
    """Headless Chromium path for Workday / SuccessFactors / Taleo / bot-protected pages."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on CI install
        raise FetchError(
            "playwright is not installed (pip install playwright && playwright install chromium)"
        ) from exc

    started = time.monotonic()
    last_error: Optional[Exception] = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        try:
            context = browser.new_context(
                user_agent=config.user_agent,
                viewport={"width": 1440, "height": 1000},
                locale="en-GB",
                timezone_id="Europe/London",
                ignore_https_errors=True,
            )
            page = context.new_page()
            page.set_default_timeout(target.timeout_s * 1000)
            for url in target.urls:
                try:
                    response = page.goto(url, wait_until=target.wait_until, timeout=target.timeout_s * 1000)
                    if target.wait_for_selector:
                        try:
                            page.wait_for_selector(target.wait_for_selector, timeout=10000)
                        except Exception:  # selector may legitimately never appear (status = closed)
                            logger.debug("[%s] wait_for_selector %r timed out", target.id, target.wait_for_selector)
                    page.wait_for_timeout(target.post_load_wait_ms)
                    html = page.content()
                    status = response.status if response else None
                    if not html or len(html) < 200:
                        raise FetchError("playwright returned an empty document for %s" % url)
                    elapsed = int((time.monotonic() - started) * 1000)
                    return FetchResult(
                        html=html,
                        final_url=page.url,
                        http_status=status,
                        engine="playwright",
                        elapsed_ms=elapsed,
                        blocked=_looks_blocked(html),
                    )
                except FetchError:
                    raise
                except Exception as exc:  # try the next fallback URL
                    last_error = exc
                    logger.debug("[%s] playwright navigation failed for %s: %s", target.id, url, exc)
            # Playwright drives a real browser, so the 4xx status check happens above; a
            # navigation error on every candidate URL is a hard failure.
            raise FetchError("playwright could not load any candidate URL: %s" % last_error)
        finally:
            browser.close()


def fetch_html(target: ProgramTarget, config: TargetsConfig) -> FetchResult:
    """Retrieve the best available HTML for a target, escalating to Chromium when needed."""
    errors: List[str] = []
    status_codes: List[Optional[int]] = []

    if target.engine == "playwright":
        return fetch_playwright(target, config)

    for url in target.urls:
        try:
            result = fetch_static(url, config)
        except FetchError as exc:
            errors.append("%s: %s" % (url, exc))
            status_codes.append(exc.status_code)
            continue
        except Exception as exc:
            errors.append("%s: %s" % (url, exc))
            status_codes.append(None)
            if target.auto_escalate and _is_tls_failure(exc):
                # The page itself is fine; our TLS stack was refused. Chromium ships its own.
                logger.info("[%s] TLS handshake refused for %s; retrying with headless Chromium", target.id, url)
                try:
                    return fetch_playwright(target, config)
                except Exception as browser_exc:
                    errors.append("playwright TLS retry failed: %s" % browser_exc)
            continue

        needs_browser = result.blocked or _looks_like_shell(result.html)
        if not needs_browser:
            # Cheap length probe: a thin shell usually means the SPA has not rendered yet.
            text_probe = re.sub(r"<[^>]+>", " ", result.html)
            if len(normalize_text(text_probe)) >= target.min_text_chars:
                return result
            needs_browser = True

        if needs_browser and target.auto_escalate:
            logger.info("[%s] escalating to headless Chromium (%s)", target.id, "blocked" if result.blocked else "thin/SPA")
            try:
                return fetch_playwright(target, config)
            except Exception as exc:
                errors.append("playwright escalation failed: %s" % exc)
                if not result.blocked:
                    return result
                continue
        return result

    # Every candidate failed: propagate the first HTTP status we saw so the caller can apply
    # a per-programme override (e.g. "404 on this URL means no intake page exists").
    first_code = next((code for code in status_codes if code is not None), None)
    first_url = target.urls[0] if target.urls else None
    raise FetchError(
        ("all candidate URLs failed: " + " | ".join(errors)) if errors else "no candidate URL",
        status_code=first_code,
        url=first_url,
    )


# --------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------


@dataclass
class Extraction:
    container_text: str
    classification_text: str
    content_sha256: str
    selector_used: str
    container_chars: int
    anchor_texts: List[str]
    link_text: str
    discovered_apply_url: Optional[str]
    soup: Any = None


def _is_xpath(selector: str) -> bool:
    stripped = selector.strip()
    return stripped.startswith(("/", "(", "./", ".//"))


def _select(soup: Any, selector: str) -> List[Any]:
    """Select with CSS, or XPath when the selector looks like one."""
    try:
        if _is_xpath(selector):
            return list(soup.xpath(selector))  # lxml-backed soups only
        return list(soup.select(selector))
    except Exception as exc:
        logger.debug("selector %r failed: %s", selector, exc)
        return []


def _element_text(element: Any) -> str:
    try:
        return element.get_text(" ", strip=True) if hasattr(element, "get_text") else str(element)
    except Exception:
        return ""


def _parse_document(html: str) -> Any:
    """Parse with the XML parser when the payload is a feed, otherwise with the HTML parser.

    Air France's status signal is an RSS facet, and lxml warns (correctly) that HTML-parsing
    an XML document is unreliable. CSS selection works the same way on either tree.
    """
    from bs4 import BeautifulSoup

    head = html.lstrip()[:400].lower()
    is_xml = head.startswith("<?xml") or "<rss" in head or "<feed" in head
    return BeautifulSoup(html, "lxml-xml" if is_xml else "lxml")


KNOWN_ATS_HOST_SUFFIXES = (
    "brassring.com",
    "successfactors.eu",
    "successfactors.com",
    "jobs2web.com",
    "myworkdayjobs.com",
    "workday.com",
    "taleo.net",
    "workable.com",
    "lumessetalentlink.com",
    "icims.com",
    "smartrecruiters.com",
    "avature.net",
    "jobvite.com",
    "greenhouse.io",
    "lever.co",
)


def _registrable_domain(url: str) -> str:
    """Best-effort registrable domain (last two labels; enough for .com/.co.uk/.fr/.hu)."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return host
    two_label_suffixes = ("co.uk", "com.au", "co.nz", "com.br", "co.jp", "org.uk", "com.hk")
    if ".".join(parts[-2:]) in two_label_suffixes and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _link_is_trustworthy(candidate: str, target: ProgramTarget) -> bool:
    """Only accept a discovered apply link from the airline's own estate or a known ATS.

    Without this guard, BA's preparation page yielded https://www.caa.co.uk/.../Apply-for-a-
    Class-1-medical-certificate (an "Apply" link for something entirely different), and Cathay's
    page yielded the "Apply for Flight Attendant" navigation link. Sending someone to the wrong
    page during a short application window is worse than sending them to the programme page.
    """
    candidate_host = (urlparse(candidate).hostname or "").lower()
    if not candidate_host:
        return False
    if any(candidate_host.endswith(suffix) for suffix in KNOWN_ATS_HOST_SUFFIXES):
        return True
    allowed = {_registrable_domain(u) for u in [target.primary_url, target.apply_url] + list(target.fallback_urls)}
    allowed.discard("")
    return _registrable_domain(candidate) in allowed


def extract(html: str, base_url: str, target: ProgramTarget) -> Extraction:
    from bs4 import Comment

    soup = _parse_document(html)

    # HTML comments must go first. Career sites routinely park a *previous* status inside one
    # (Aer Lingus leaves "Applications ... are now open." commented out next to the live
    # "now closed" sentence), and BeautifulSoup's get_text() includes comment text - so
    # leaving them in would make the monitor report whichever state the author commented out.
    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()

    for tag in soup(["script", "style", "noscript", "template", "svg", "iframe", "form"]):
        tag.decompose()

    # --- primary content container -----------------------------------------------------
    container = None
    selector_used = ""
    for selector in target.content_selectors:
        candidates = _select(soup, selector)
        if not candidates:
            continue
        best = max(candidates, key=lambda el: len(_element_text(el)))
        if len(normalize_text(_element_text(best))) >= 40:
            container = best
            selector_used = selector
            break
    if container is None:
        container = soup.body or soup
        selector_used = "fallback:document"

    container_raw = normalize_text(_element_text(container))
    if len(container_raw) < 40:
        raise ExtractionError(
            "content container %r yielded only %d chars for %s"
            % (selector_used, len(container_raw), target.id)
        )
    container_scrubbed = scrub_volatile(container_raw)

    # --- anchors ------------------------------------------------------------------------
    # Button/link labels are strong status evidence ("Apply now" vs "Register your interest"),
    # so they join the classification text but never the hash.
    anchor_texts: List[str] = []
    seen_anchors = set()
    for anchor in soup.find_all("a"):
        label = normalize_text(anchor.get_text(" ", strip=True))
        if not label or len(label) > 80:
            continue
        key = label.lower()
        if key in seen_anchors:
            continue
        seen_anchors.add(key)
        anchor_texts.append(label)
    anchor_blob = " || ".join(anchor_texts[:400])

    classification_text = normalize_text(container_scrubbed + LINKS_SEPARATOR + anchor_blob)
    content_sha256 = sha256_of(container_scrubbed)

    # --- best apply link ----------------------------------------------------------------
    discovered: Optional[str] = None
    apply_words = re.compile(
        r"(?i)\b(apply|application|register|sign\s*up|join|enrol|enroll|vacanc|job|career|"
        r"jelentkez|postuler|candidat)\b"
    )
    best_score = 0
    for selector in target.apply_link_selectors:
        for anchor in _select(soup, selector):
            href = anchor.get("href") if hasattr(anchor, "get") else None
            if not href:
                # XML feeds (Air France's RSS offer facet) carry URLs as element *text*
                # inside <link> elements rather than as an href attribute.
                text_value = _element_text(anchor)
                if text_value.startswith(("http://", "https://")):
                    href = text_value.strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            # A login / account page is never an application landing page. The live BA page
            # offered "apply.ba.com/jobs/login/" as an "Apply" link, which would have sent the
            # user to a sign-in form instead of the programme.
            if re.search(r"(?i)/(?:login|log-in|signin|sign-in|signup\?|account|profile|register\?redirect)", href):
                continue
            label_probe = _element_text(anchor)
            if re.search(r"(?i)\b(?:log\s?in|sign\s?in|my\s+account|profile)\b", label_probe) and not re.search(
                r"(?i)\b(?:apply|register\s+your\s+interest|job\s+alerts?)\b", label_probe
            ):
                continue
            label = _element_text(anchor)
            haystack = "%s %s" % (label, href)
            if not apply_words.search(haystack):
                continue
            score = 0
            if re.search(r"(?i)\bapply\b", label):
                score += 5
            if re.search(r"(?i)register your interest|talent pool|join our talent", label):
                score += 3
            if re.search(r"(?i)apply|application|career|job|vacanc", href):
                score += 2
            if score > best_score and _link_is_trustworthy(urljoin(base_url, href), target):
                best_score = score
                discovered = urljoin(base_url, href)

    return Extraction(
        container_text=container_scrubbed,
        classification_text=classification_text,
        content_sha256=content_sha256,
        selector_used=selector_used,
        container_chars=len(container_scrubbed),
        anchor_texts=anchor_texts,
        link_text=anchor_blob,
        discovered_apply_url=discovered,
        soup=soup,
    )


# --------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------


@dataclass
class Classification:
    status: str
    evidence: str
    rule_source: str
    rule_note: str
    matched_text: str
    probe_counts: Dict[int, int] = field(default_factory=dict)


def _evidence_snippet(text: str, span: Optional[Sequence[int]], matched: str) -> str:
    """Quote the sentence that actually decided the status.

    A raw ±N-character window starts and ends mid-word ("...ways employee benefits as soon as
    you join Preparation materials Interested in applying? The first step is to register here
    to view..."), which reads badly in an alert and in the widget. Trim to the containing
    sentence instead, and never cross into the appended link list.
    """
    if not span or len(span) != 2:
        return re.sub(r"\s+", " ", matched).strip()[:320]

    start, end = span
    if start > len(text) or end > len(text):
        return re.sub(r"\s+", " ", matched).strip()[:320]

    # Never let a quote straddle the seam between the page body and the appended link list.
    seam = text.find("--- LINKS ---")
    if seam != -1 and end > seam:
        end = max(seam - 1, start)

    delimiters = (". ", "! ", "? ", "\n", "|", " · ")
    left = 0
    for delimiter in delimiters:
        found = text.rfind(delimiter, 0, start)
        left = max(left, found + len(delimiter))
    right = len(text)
    for delimiter in delimiters:
        found = text.find(delimiter, end)
        if found != -1:
            right = min(right, found + 1)
    snippet = text[left:right]
    if len(snippet) < 12 or len(snippet) > 340:
        snippet = text[max(0, start - 110): min(len(text), end + 110)]
    snippet = re.sub(r"\s+", " ", snippet).strip()
    # Drop partial leading words left behind by the delimiter search ("art date ...").
    for _ in range(2):
        first_word = snippet.split(" ", 1)[0] if " " in snippet else ""
        if first_word and first_word[0].islower() and not first_word.isdigit():
            snippet = snippet.split(" ", 1)[1]
        else:
            break
    # If the containing "sentence" is really just navigation chrome running into the wording,
    # quote the matched phrase itself: that is what decided the status and what a human can
    # verify on the page.
    if len(snippet) > 220:
        snippet = re.sub(r"\s+", " ", matched).strip()
    return snippet[:320]


def classify(target: ProgramTarget, extraction: Extraction) -> Classification:
    """First matching rule wins. Ordering in targets.json is semantically meaningful."""
    link_text = extraction.link_text
    segments = [(extraction.container_text, 0)]
    if link_text:
        segments.append((link_text, len(extraction.container_text) + len(LINKS_SEPARATOR)))
    ctx = RuleContext(
        classification_text=extraction.classification_text,
        container_text=extraction.container_text,
        select=lambda selector: _select(extraction.soup, selector),
        segments=segments,
    )

    evaluated: List[Dict[str, Any]] = []
    for rule in target.rules:
        outcome = rule.matches(ctx)
        if outcome is None:
            continue
        evaluated.append(
            {
                "rule": rule.source,
                "status": rule.status,
                "note": rule.note,
                "matched": outcome["matched"],
            }
        )
        if rule.status == STATUS_UNKNOWN:
            # An explicit "we cannot tell" rule (captcha wall, notice page) must beat the
            # fallback wording: reporting CLOSED here would silently hide a broken scraper.
            return Classification(
                status=STATUS_UNKNOWN,
                evidence=_evidence_snippet(ctx.classification_text, outcome["span"], outcome["matched"]),
                rule_source=rule.source,
                rule_note=rule.note,
                matched_text=outcome["matched"],
                probe_counts=ctx.probe_counts,
            )
        evidence = _evidence_snippet(ctx.classification_text, outcome["span"], outcome["matched"])
        if outcome.get("source") == "text" and outcome["span"]:
            seam = ctx.classification_text.find("--- LINKS ---")
            if seam != -1 and outcome["span"][0] > seam:
                # A link label is a whole, short phrase; quote it verbatim.
                evidence = "link text: " + re.sub(r"\s+", " ", outcome["matched"]).strip()[:160]
        return Classification(
            status=rule.status,
            evidence=evidence,
            rule_source=rule.source,
            rule_note=rule.note,
            matched_text=outcome["matched"],
            probe_counts=ctx.probe_counts,
        )

    return Classification(
        status=target.fallback_status,
        evidence=(
            target.fallback_note
            or "no explicit status wording matched; fell back to %s" % target.fallback_status
        ),
        rule_source="fallback",
        rule_note=target.fallback_note,
        matched_text="",
        probe_counts=ctx.probe_counts,
    )


# --------------------------------------------------------------------------------------
# Programme check + state merge
# --------------------------------------------------------------------------------------


@dataclass
class CheckOutcome:
    record: Dict[str, Any]
    ok: bool


def _http_status_override(target: ProgramTarget, exc: Exception) -> Optional[str]:
    """Return the configured status for this failure's HTTP code, if the programme maps one."""
    code = getattr(exc, "status_code", None)
    if code is None:
        return None
    return target.http_status_overrides.get(str(code))


def _previous_by_id(previous: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not previous:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for entry in previous.get("programs", []) or []:
        if isinstance(entry, dict) and entry.get("id"):
            out[str(entry["id"])] = entry
    return out


def fetch_secondary_text(url: str, config: TargetsConfig) -> str:
    """Fetch a fallback source (JSON or XML feed) and return it as flat text.

    Used only when the primary page produced no decisive answer - typically because a WAF
    served an interstitial. Aer Lingus is the motivating case: every aerlingus.com path
    returns an Imperva block page, while the recruitment feed that actually lists its cadet
    vacancies is a plain JSON endpoint.
    """
    import httpx

    headers = {"User-Agent": config.user_agent, "Accept": "application/json,text/xml,*/*"}
    with httpx.Client(follow_redirects=True, timeout=config.request_timeout_s, headers=headers) as client:
        response = client.get(url)
        if response.status_code >= 400:
            raise FetchError("HTTP %s for secondary source %s" % (response.status_code, url), status_code=response.status_code, url=url)
        return response.text


def check_program(
    target: ProgramTarget,
    config: TargetsConfig,
    previous: Optional[Dict[str, Any]],
    fixtures_dir: Optional[Path],
) -> CheckOutcome:
    now = utc_now_iso()
    prev = previous or {}
    prev_status = str(prev.get("status") or "")
    prev_failures = int(prev.get("consecutive_failures") or 0)

    base: Dict[str, Any] = {
        "id": target.id,
        "airline": target.airline,
        "program": target.program,
        "passport": target.passport,
        "passport_label": target.passport_label,
        "rtw_scope": target.rtw_scope,
        "apply_url": target.apply_url,
    }
    if target.watch_urls:
        base["watch_urls"] = list(target.watch_urls)

    try:
        if fixtures_dir is not None:
            fixture = None
            for candidate in (fixtures_dir / ("%s.html" % target.id), fixtures_dir / ("%s.txt" % target.id)):
                if candidate.exists():
                    fixture = candidate
                    break
            if fixture is None:
                raise FetchError("no fixture for %s in %s" % (target.id, fixtures_dir))
            html = fixture.read_text(encoding="utf-8", errors="replace")
            fetch = FetchResult(
                html=html,
                final_url=target.primary_url,
                http_status=200,
                engine="fixture",
                elapsed_ms=0,
            )
        else:
            fetch = fetch_html(target, config)

        extraction = extract(fetch.html, fetch.final_url, target)
        outcome = classify(target, extraction)

        # Rescue path: if the primary page was uninformative (bot wall, maintenance, or simply
        # no recognisable wording) try the configured secondary feeds. Their text is appended
        # to the classification text and the rules run again. An UNKNOWN primary is only
        # overridden by a *decisive* secondary match - never by another fallback - so a
        # blocked page still surfaces as UNKNOWN rather than being silently called CLOSED.
        secondary_used: Optional[str] = None
        if target.secondary_text_urls and (
            outcome.status == STATUS_UNKNOWN or outcome.rule_source == "fallback"
        ):
            for secondary_url in target.secondary_text_urls:
                try:
                    secondary_text = fetch_secondary_text(secondary_url, config)
                except Exception as exc:
                    logger.debug("[%s] secondary source %s failed: %s", target.id, secondary_url, exc)
                    continue
                if not secondary_text.strip():
                    continue
                # The secondary feed is classified ON ITS OWN, not merged with the blocked
                # page: merging would leave the bot-wall text in front of it, so the guard rule
                # would keep winning and the rescue could never fire.
                secondary_extraction = dataclasses.replace(
                    extraction,
                    container_text=normalize_text(secondary_text),
                    link_text="",
                    classification_text=normalize_text(secondary_text),
                )
                secondary_outcome = classify(target, secondary_extraction)
                if secondary_outcome.rule_source == "fallback" or secondary_outcome.status == STATUS_UNKNOWN:
                    logger.info(
                        "[%s] secondary source %s contained no decisive wording", target.id, secondary_url
                    )
                    continue
                outcome = Classification(
                    status=secondary_outcome.status,
                    evidence="[secondary: %s] %s" % (secondary_url, secondary_outcome.evidence),
                    rule_source=secondary_outcome.rule_source,
                    rule_note=secondary_outcome.rule_note,
                    matched_text=secondary_outcome.matched_text,
                    probe_counts=secondary_outcome.probe_counts,
                )
                secondary_used = secondary_url
                logger.info("[%s] status %s from secondary source %s", target.id, outcome.status, secondary_url)
                break

        if outcome.status == STATUS_ERROR:
            raise ExtractionError("rule engine emitted ERROR for %s" % target.id)

        resolved_apply = target.apply_url if target.prefer_configured_apply_url else (
            extraction.discovered_apply_url or target.apply_url
        )
        # Prefer a *discovered* apply link only when it is a real navigation target.
        if resolved_apply and _strip_url_noise(resolved_apply) == _strip_url_noise(target.primary_url):
            resolved_apply = target.apply_url

        changed_status = outcome.status != prev_status
        record = dict(base)
        record.update(
            {
                "status": outcome.status,
                "previous_status": prev_status or None,
                "status_changed": bool(changed_status and prev_status),
                "changed_at": now if changed_status else (prev.get("changed_at") or now),
                "checked_at": now,
                "content_changed": bool(
                    prev.get("content_sha256") and prev.get("content_sha256") != extraction.content_sha256
                ),
                "content_sha256": extraction.content_sha256,
                "container_selector": extraction.selector_used,
                "container_chars": extraction.container_chars,
                "source_url": fetch.final_url,
                "apply_url": resolved_apply,
                "engine": fetch.engine,
                "http_status": fetch.http_status,
                "latency_ms": fetch.elapsed_ms,
                "evidence": outcome.evidence,
                "matched_rule": outcome.rule_source,
                "matched_rule_note": outcome.rule_note,
                "matched_text": outcome.matched_text,
                "secondary_source": secondary_used,
                "consecutive_failures": 0,
                "error": None,
            }
        )
        logger.info(
            "[%s] %s (%s, %s, %dms) :: %s",
            target.id,
            outcome.status,
            fetch.engine,
            extraction.selector_used,
            fetch.elapsed_ms,
            outcome.evidence[:110],
        )
        return CheckOutcome(record=record, ok=True)

    except Exception as exc:
        # Some pages disappear on purpose. A mapped HTTP status is a *classified* result, not
        # an error: it keeps the widget honest instead of freezing on a stale status forever.
        override = _http_status_override(target, exc)
        if override:
            code = getattr(exc, "status_code", None)
            changed = override != prev_status
            record = dict(base)
            record.update(
                {
                    "status": override,
                    "previous_status": prev_status or None,
                    "status_changed": bool(changed and prev_status),
                    "changed_at": now if changed else (prev.get("changed_at") or now),
                    "checked_at": now,
                    "content_changed": False,
                    "content_sha256": None,
                    "container_selector": None,
                    "container_chars": None,
                    "source_url": getattr(exc, "url", None) or target.primary_url,
                    "apply_url": target.apply_url,
                    "engine": "static",
                    "http_status": code,
                    "latency_ms": None,
                    "evidence": target.http_status_override_note
                    or "HTTP %s from the programme page; mapped to %s by configuration." % (code, override),
                    "matched_rule": "http_status_override",
                    "matched_rule_note": target.http_status_override_note,
                    "matched_text": "HTTP %s" % code,
                    "consecutive_failures": 0,
                    "error": None,
                    "warnings": ["http_status_%s_mapped_to_%s" % (code, override)],
                }
            )
            logger.info("[%s] %s (HTTP %s mapped by config)", target.id, override, code)
            return CheckOutcome(record=record, ok=True)

        failures = prev_failures + 1
        logger.error("[%s] check failed (%d consecutive): %s", target.id, failures, exc)
        record = dict(base)
        record.update(
            {
                "status": prev_status or STATUS_ERROR,
                "previous_status": prev_status or None,
                "status_changed": False,
                "changed_at": prev.get("changed_at") or now,
                "checked_at": now,
                "content_changed": False,
                "content_sha256": prev.get("content_sha256"),
                "container_selector": prev.get("container_selector"),
                "container_chars": prev.get("container_chars"),
                "source_url": prev.get("source_url") or target.primary_url,
                "apply_url": prev.get("apply_url") or target.apply_url,
                "engine": prev.get("engine"),
                "http_status": prev.get("http_status"),
                "latency_ms": None,
                "evidence": prev.get("evidence") or "no successful check yet",
                "matched_rule": prev.get("matched_rule"),
                "matched_rule_note": prev.get("matched_rule_note"),
                "matched_text": prev.get("matched_text"),
                "consecutive_failures": failures,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "stale": True,
            }
        )
        return CheckOutcome(record=record, ok=False)


def build_summary(records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"open": 0, "interest": 0, "closed": 0, "unknown": 0, "error": 0}
    for record in records:
        status = str(record.get("status", "")).upper()
        if status == STATUS_OPEN:
            summary["open"] += 1
        elif status == STATUS_INTEREST:
            summary["interest"] += 1
        elif status == STATUS_CLOSED:
            summary["closed"] += 1
        elif status == STATUS_ERROR:
            summary["error"] += 1
        else:
            summary["unknown"] += 1
    return summary


def serialize_status(records: Sequence[Dict[str, Any]], config: TargetsConfig, generated_at: str) -> str:
    document = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "generated_by": "pilot-tracker/monitor.py",
        "summary": build_summary(records),
        "programs": list(records),
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def diff_transitions(
    records: Sequence[Dict[str, Any]],
    previous: Optional[Dict[str, Any]],
    alert_on_open: bool = True,
    alert_on_interest: bool = False,
    alert_on_closed: bool = False,
) -> List[Dict[str, Any]]:
    """Transitions worth notifying about. Only *newly* actionable states qualify."""
    prev_map = _previous_by_id(previous)
    transitions: List[Dict[str, Any]] = []
    for record in records:
        pid = str(record.get("id"))
        prev = prev_map.get(pid, {})
        old = str(prev.get("status") or "NEW")
        new = str(record.get("status") or "")
        if new == STATUS_ERROR or old == new:
            continue

        trigger = None
        if alert_on_open and new == STATUS_OPEN and old != STATUS_OPEN:
            trigger = "open"
        elif alert_on_interest and new == STATUS_INTEREST and old != STATUS_INTEREST:
            trigger = "interest"
        elif alert_on_closed and new == STATUS_CLOSED and old in (STATUS_OPEN, STATUS_INTEREST):
            trigger = "closed"
        if not trigger:
            continue

        transitions.append(
            {
                "id": pid,
                "airline": record.get("airline"),
                "program": record.get("program"),
                "passport": record.get("passport"),
                "passport_label": record.get("passport_label"),
                "rtw_scope": record.get("rtw_scope"),
                "from": old,
                "to": new,
                "trigger": trigger,
                "first_run": pid not in prev_map,
                "detected_at": record.get("checked_at"),
                "apply_url": record.get("apply_url"),
                "source_url": record.get("source_url"),
                "evidence": record.get("evidence"),
            }
        )
    return transitions


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def log_summary_table(records: Sequence[Dict[str, Any]]) -> None:
    logger.info("=" * 92)
    logger.info("%-14s %-10s %-9s %-10s %s", "AIRLINE", "STATUS", "PASSPORT", "CHANGED", "EVIDENCE")
    logger.info("-" * 92)
    for record in records:
        logger.info(
            "%-14s %-10s %-9s %-10s %s",
            str(record.get("airline", ""))[:14],
            str(record.get("status", "")),
            str(record.get("passport", "")),
            "yes" if record.get("status_changed") else "no",
            str(record.get("evidence") or "")[:44],
        )
    logger.info("=" * 92)


def write_step_summary(records: Sequence[Dict[str, Any]], transitions: Sequence[Dict[str, Any]], path: Optional[str]) -> None:
    """Publish a Markdown table into the GitHub Actions run summary when available."""
    if not path:
        return
    lines = ["## Pilot cadet programme status", ""]
    summary = build_summary(records)
    lines.append(
        "**OPEN: %d** · INTEREST: %d · CLOSED: %d · UNKNOWN: %d · ERROR: %d"
        % (summary["open"], summary["interest"], summary["closed"], summary["unknown"], summary["error"])
    )
    lines.append("")
    lines.append("| Airline | Programme | Status | Passport | Evidence |")
    lines.append("| --- | --- | --- | --- | --- |")
    for record in records:
        lines.append(
            "| %s | %s | `%s` | %s | %s |"
            % (
                record.get("airline", ""),
                record.get("program", ""),
                record.get("status", ""),
                record.get("passport_label") or record.get("passport") or "",
                re.sub(r"\|", "/", str(record.get("evidence") or ""))[:160],
            )
        )
    if transitions:
        lines.append("")
        lines.append("### Alerts dispatched")
        for transition in transitions:
            lines.append(
                "- **%s** %s → %s ([apply](%s))"
                % (transition.get("airline"), transition.get("from"), transition.get("to"), transition.get("apply_url"))
            )
    else:
        lines.append("")
        lines.append("_No status transitions this run._")
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:  # pragma: no cover
        logger.debug("could not write step summary: %s", exc)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Passively check airline pilot cadet programme status and update status.json.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--targets", default=str(here / "targets.json"), help="programme catalogue")
    parser.add_argument("--output", default=str(here.parent / "status.json"), help="status.json to write")
    parser.add_argument(
        "--transitions-out",
        default=str(here.parent / "build" / "transitions.json"),
        help="where to write transitions for the notifier",
    )
    parser.add_argument("--program", action="append", default=None, help="limit to this programme id (repeatable)")
    parser.add_argument("--engine", choices=["static", "playwright"], default=None, help="force a fetch engine")
    parser.add_argument("--offline", action="store_true", help="replay captured HTML instead of the network")
    parser.add_argument("--fixtures-dir", default=str(here / "fixtures"), help="fixtures directory for --offline")
    parser.add_argument("--no-notify", action="store_true", help="never dispatch alerts from this process")
    parser.add_argument(
        "--notify",
        action="store_true",
        help="import notifier and dispatch alerts for this run's transitions",
    )
    parser.add_argument("--alert-on-interest", action="store_true", help="also alert on INTEREST transitions")
    parser.add_argument("--alert-on-closed", action="store_true", help="also alert when a window closes")
    parser.add_argument("--fail-on-error", action="store_true", help="exit 1 when any programme failed to check")
    parser.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    targets_path = Path(args.targets)
    output_path = Path(args.output)
    transitions_path = Path(args.transitions_out)

    try:
        config = load_targets(targets_path)
    except ConfigError as exc:
        logger.error("configuration error: %s", exc)
        return 1

    selected = config.programs
    if args.program:
        wanted = {p.lower() for p in args.program}
        selected = [p for p in selected if p.id.lower() in wanted]
        if not selected:
            logger.error("no programme matched --program %s", args.program)
            return 1

    previous: Optional[Dict[str, Any]] = None
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
            logger.info("loaded previous state (%d programmes) from %s", len(previous.get("programs", []) or []), output_path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("could not read previous status.json (%s); treating this as a first run", exc)

    prev_map = _previous_by_id(previous)
    fixtures_dir = Path(args.fixtures_dir) if args.offline else None
    if args.offline and not fixtures_dir.exists():
        logger.error("--offline requested but fixtures dir %s does not exist", fixtures_dir)
        return 1

    records: List[Dict[str, Any]] = []
    for index, target in enumerate(selected):
        if args.engine:
            target.engine = args.engine
        if index and fixtures_dir is None:
            delay = config.polite_delay_s + random.uniform(0, 1.0)
            logger.debug("politeness delay %.1fs", delay)
            time.sleep(delay)
        outcome = check_program(target, config, prev_map.get(target.id), fixtures_dir)
        records.append(outcome.record)

    generated_at = utc_now_iso()

    # In --program (partial) mode, keep untouched programmes verbatim so status.json stays whole.
    if args.program and previous:
        touched = {record["id"] for record in records}
        for entry in previous.get("programs", []) or []:
            if isinstance(entry, dict) and entry.get("id") not in touched:
                records.append(entry)
        order = {p.id: i for i, p in enumerate(config.programs)}
        records.sort(key=lambda record: order.get(str(record.get("id")), 999))

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = serialize_status(records, config, generated_at)
        previous_payload = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        if previous_payload != payload:
            output_path.write_text(payload, encoding="utf-8")
            logger.info("wrote %s", output_path)
        else:
            logger.info("%s unchanged (no content churn)", output_path)
    except OSError as exc:
        logger.error("could not write %s: %s", output_path, exc)
        return 1

    transitions = diff_transitions(
        records,
        previous,
        alert_on_open=True,
        alert_on_interest=args.alert_on_interest,
        alert_on_closed=args.alert_on_closed,
    )

    try:
        transitions_path.parent.mkdir(parents=True, exist_ok=True)
        transitions_path.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "generated_at": generated_at,
                    "transitions": transitions,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        logger.info("wrote %s (%d transitions)", transitions_path, len(transitions))
    except OSError as exc:
        logger.error("could not write %s: %s", transitions_path, exc)

    log_summary_table(records)
    write_step_summary(records, transitions, os.environ.get("GITHUB_STEP_SUMMARY"))

    if args.notify and not args.no_notify:
        try:
            import notifier  # local sibling module

            notifier.dispatch_transitions(transitions, dry_run=False)
        except Exception as exc:  # notification must never break the monitor
            logger.error("notification dispatch failed: %s", exc)

    failed = [record for record in records if record.get("consecutive_failures")]
    if failed:
        logger.warning("%d programme(s) failed this run: %s", len(failed), ", ".join(r["id"] for r in failed))
    if args.fail_on_error and failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
