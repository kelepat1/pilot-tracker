"""
Offline test suite for monitor.py.

Every test runs without network access: the fixtures in ``scraper/fixtures`` replay the
markup shapes observed on the live career portals, so the rule engine, the hash scrubber and
the transition logic can be verified in CI before any secret exists.
"""

import json
import re
from pathlib import Path

import pytest

import monitor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
OPEN_FIXTURES = FIXTURES / "open_variants"
TARGETS = Path(__file__).resolve().parents[1] / "targets.json"

EXPECTED_IDS = [
    "ba-speedbird",
    "jet2-flightpath",
    "tui-mpl",
    "aerlingus-future-pilot",
    "airfrance-cadets",
    "wizzair-pilot-academy",
    "cathay-cadet",
]

# Programme id -> status the fixture must produce.
EXPECTED_OFFLINE_STATUS = {
    "ba-speedbird": monitor.STATUS_INTEREST,  # closed 2026 window + job-alert registration
    "jet2-flightpath": monitor.STATUS_INTEREST,  # 'Applications Are Now Closed' + job alerts
    "tui-mpl": monitor.STATUS_CLOSED,  # no intake page, no notification route
    "aerlingus-future-pilot": monitor.STATUS_CLOSED,
    "airfrance-cadets": monitor.STATUS_OPEN,
    "wizzair-pilot-academy": monitor.STATUS_OPEN,
    "cathay-cadet": monitor.STATUS_CLOSED,  # 'not currently open for applications'
}


@pytest.fixture(scope="module")
def config():
    return monitor.load_targets(TARGETS)


@pytest.fixture(scope="module")
def targets_by_id(config):
    return {target.id: target for target in config.programs}


# --------------------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------------------


def test_catalogue_covers_every_requested_programme(config):
    assert [target.id for target in config.programs] == EXPECTED_IDS


def test_passport_tags_match_the_brief(targets_by_id):
    expected = {
        "ba-speedbird": ("UK", "🇬🇧 UK", "UK Right to Work"),
        "jet2-flightpath": ("UK", "🇬🇧 UK", "UK Right to Work"),
        "tui-mpl": ("UK", "🇬🇧 UK", "UK Right to Work"),
        "aerlingus-future-pilot": ("EU", "🇪🇺 EU", "EU/EEA Right to Work"),
        "airfrance-cadets": ("EU", "🇪🇺 EU", "EU/EEA Right to Work"),
        "wizzair-pilot-academy": ("EU", "🇪🇺 EU", "EU/EEA Right to Work"),
        "cathay-cadet": ("Global", "🌍 Global", "International / Targeted RTW"),
    }
    for pid, (passport, label, scope) in expected.items():
        target = targets_by_id[pid]
        assert target.passport == passport, pid
        assert target.passport_label == label, pid
        assert target.rtw_scope == scope, pid


def test_every_programme_has_absolute_https_urls_and_rules(config):
    for target in config.programs:
        assert target.primary_url.startswith("https://"), target.id
        assert target.apply_url.startswith("https://"), target.id
        assert target.rules, target.id
        assert target.fallback_status in monitor.VALID_STATUSES, target.id


def test_rule_ordering_puts_negations_before_affirmations(targets_by_id):
    """'not currently open' contains the word 'open': the negation rule must come first."""
    rules = targets_by_id["cathay-cadet"].rules
    statuses_and_patterns = [(rule.status, rule.pattern.pattern if rule.pattern else "") for rule in rules]

    negation_index = next(
        index
        for index, (status, pattern) in enumerate(statuses_and_patterns)
        if status == monitor.STATUS_CLOSED and "not" in pattern and "open" in pattern
    )
    positive_open_index = next(
        index
        for index, (status, pattern) in enumerate(statuses_and_patterns)
        if status == monitor.STATUS_OPEN and "open" in pattern and "not" not in pattern
    )
    assert negation_index < positive_open_index


# --------------------------------------------------------------------------------------
# Offline classification
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("pid,expected_status", sorted(EXPECTED_OFFLINE_STATUS.items()))
def test_fixture_classifies_as_expected(config, targets_by_id, pid, expected_status):
    outcome = monitor.check_program(targets_by_id[pid], config, previous=None, fixtures_dir=FIXTURES)
    assert outcome.ok, outcome.record.get("error")
    assert outcome.record["status"] == expected_status, (
        "%s classified as %s (evidence: %s)"
        % (pid, outcome.record["status"], outcome.record.get("evidence"))
    )
    assert outcome.record["consecutive_failures"] == 0
    assert outcome.record["content_sha256"]
    assert outcome.record["evidence"]


def test_english_engine_rules_are_language_aware(config, targets_by_id):
    """Air France is French-language and Wizz Air can fall back to Hungarian."""
    air_france = targets_by_id["airfrance-cadets"]
    patterns = " ".join(rule.pattern.pattern for rule in air_france.rules if rule.pattern)
    assert "candidatures" in patterns.lower()

    wizz = targets_by_id["wizzair-pilot-academy"]
    wizz_patterns = " ".join(rule.pattern.pattern for rule in wizz.rules if rule.pattern)
    assert "jelentkez" in wizz_patterns.lower()


def test_listing_probe_detects_open_vacancies(config, targets_by_id):
    """Wizz Air's fixture has no 'open' sentence: only two cadet listings exist."""
    outcome = monitor.check_program(
        targets_by_id["wizzair-pilot-academy"], config, previous=None, fixtures_dir=FIXTURES
    )
    assert outcome.record["status"] == monitor.STATUS_OPEN
    assert outcome.record["matched_text"].startswith("probe="), outcome.record["matched_text"]


@pytest.mark.parametrize("pid", ["ba-speedbird", "jet2-flightpath"])
def test_reopened_window_is_detected_as_open(config, targets_by_id, pid):
    """The whole point of the system: the window reopening must classify as OPEN.

    These fixtures model the two real reopening shapes - new 'applications are now open'
    wording (BA) and the CTA anchor gaining a live apply link (Jet2, whose BrassRing link is
    empty while the window is shut).
    """
    outcome = monitor.check_program(targets_by_id[pid], config, previous=None, fixtures_dir=OPEN_FIXTURES)
    assert outcome.ok, outcome.record.get("error")
    assert outcome.record["status"] == monitor.STATUS_OPEN, outcome.record["evidence"]


def test_captcha_interstitial_reports_unknown_not_closed(config, targets_by_id):
    """A bot wall must surface as UNKNOWN so a blind scraper is visible, never as CLOSED."""
    html = (FIXTURES / "_blocked-interstitial.html").read_text(encoding="utf-8")
    target = targets_by_id["ba-speedbird"]
    extraction = monitor.extract(html, target.primary_url, target)
    classification = monitor.classify(target, extraction)
    assert classification.status == monitor.STATUS_UNKNOWN


def test_interest_wins_over_closed_when_a_talent_pool_is_offered(config, targets_by_id):
    """'Applications Are Now Closed' + a job-alert route is an actionable INTEREST state."""
    outcome = monitor.check_program(targets_by_id["jet2-flightpath"], config, previous=None, fixtures_dir=FIXTURES)
    assert outcome.record["status"] == monitor.STATUS_INTEREST
    assert "job alert" in outcome.record["evidence"].lower()


def test_merely_watching_a_page_is_not_interest(config, targets_by_id):
    """TUI's 'keep an eye on this page' offers no route, so it must stay CLOSED."""
    outcome = monitor.check_program(targets_by_id["tui-mpl"], config, previous=None, fixtures_dir=FIXTURES)
    assert outcome.record["status"] == monitor.STATUS_CLOSED
    assert "closed" in outcome.record["evidence"].lower()


# --------------------------------------------------------------------------------------
# Hashing / volatility
# --------------------------------------------------------------------------------------


def test_volatile_noise_does_not_change_the_content_hash(config, targets_by_id):
    """Timestamps, nonces, session ids and copyright years must not flip the hash."""
    target = targets_by_id["ba-speedbird"]
    base_html = (FIXTURES / "ba-speedbird.html").read_text(encoding="utf-8")

    noisy_html = (
        base_html.replace("2026-02-12T09:41:00Z", "2026-09-18T04:12:59Z")
        .replace("09:41", "17:03")
        .replace("4f8ba2c1d9e07a35bc1f2d6e8a90bb11", "aa11bb22cc33dd44ee55ff6677889900")
        .replace("&copy; 2026", "&copy; 2027")
        .replace("Page last updated: 12 February 2026 at 09:41 by the careers team.", "Page last updated: 18 September 2026 at 17:03 by the careers team.")
    )

    first = monitor.extract(base_html, target.primary_url, target)
    second = monitor.extract(noisy_html, target.primary_url, target)

    assert first.content_sha256 == second.content_sha256
    assert first.container_chars == second.container_chars


def test_real_content_change_does_change_the_hash(config, targets_by_id):
    target = targets_by_id["ba-speedbird"]
    base_html = (FIXTURES / "ba-speedbird.html").read_text(encoding="utf-8")
    # The fixture wraps this sentence across lines, so match with flexible whitespace.
    changed_html = re.sub(
        r"Applications for 2026 have now\s+closed\.",
        "Applications for 2027 are now open.",
        base_html,
    )
    assert changed_html != base_html, "fixture wording changed - update this test"
    first = monitor.extract(base_html, target.primary_url, target)
    second = monitor.extract(changed_html, target.primary_url, target)
    assert first.content_sha256 != second.content_sha256


def test_scrubber_replaces_transient_tokens():
    scrubbed = monitor.scrub_volatile(
        "Updated 2026-02-12T09:41:00Z token=abc123 "
        "hash 4f8ba2c1d9e07a35bc1f2d6e8a90bb11 © 2026"
    )
    assert "<TS>" in scrubbed or "<VOLATILE>" in scrubbed
    assert "<TOKEN>" in scrubbed
    assert "<YEAR>" in scrubbed
    assert "4f8ba2c1d9e07a35bc1f2d6e8a90bb11" not in scrubbed


# --------------------------------------------------------------------------------------
# HTTP status overrides
# --------------------------------------------------------------------------------------


def test_mapped_404_is_classified_not_an_error(config, targets_by_id, monkeypatch):
    """TUI deleted its MPL page: 404 there is a real, classified state."""
    target = targets_by_id["tui-mpl"]
    assert target.http_status_overrides.get("404") == monitor.STATUS_CLOSED

    def fail(*args, **kwargs):
        raise monitor.FetchError("HTTP 404 for %s" % target.primary_url, status_code=404, url=target.primary_url)

    monkeypatch.setattr(monitor, "fetch_html", fail)
    outcome = monitor.check_program(target, config, previous=None, fixtures_dir=None)

    assert outcome.ok
    assert outcome.record["status"] == monitor.STATUS_CLOSED
    assert outcome.record["consecutive_failures"] == 0
    assert outcome.record["matched_rule"] == "http_status_override"
    assert outcome.record["http_status"] == 404


def test_unmapped_failure_keeps_last_known_status(config, targets_by_id, monkeypatch):
    target = targets_by_id["ba-speedbird"]
    previous = {
        "status": monitor.STATUS_INTEREST,
        "changed_at": "2026-02-01T08:00:00Z",
        "content_sha256": "deadbeef",
        "consecutive_failures": 1,
    }

    def fail(*args, **kwargs):
        raise monitor.FetchError("HTTP 503 for %s" % target.primary_url, status_code=503, url=target.primary_url)

    monkeypatch.setattr(monitor, "fetch_html", fail)
    outcome = monitor.check_program(target, config, previous=previous, fixtures_dir=None)

    assert not outcome.ok
    assert outcome.record["status"] == monitor.STATUS_INTEREST  # last known kept
    assert outcome.record["consecutive_failures"] == 2
    assert outcome.record["stale"] is True
    assert "503" in outcome.record["error"]


# --------------------------------------------------------------------------------------
# Transitions
# --------------------------------------------------------------------------------------


def _record(pid, status, airline="X", apply_url="https://example.com/apply"):
    return {
        "id": pid,
        "airline": airline,
        "program": "Programme",
        "passport": "UK",
        "passport_label": "🇬🇧 UK",
        "status": status,
        "checked_at": "2026-02-12T08:00:00Z",
        "apply_url": apply_url,
        "source_url": "https://example.com/",
        "evidence": "evidence",
    }


def test_transition_to_open_is_alerted():
    previous = {"programs": [_record("ba-speedbird", monitor.STATUS_CLOSED)]}
    records = [_record("ba-speedbird", monitor.STATUS_OPEN)]
    transitions = monitor.diff_transitions(records, previous)
    assert len(transitions) == 1
    assert transitions[0]["trigger"] == "open"
    assert transitions[0]["from"] == monitor.STATUS_CLOSED
    assert transitions[0]["to"] == monitor.STATUS_OPEN


def test_no_alert_when_status_is_unchanged():
    previous = {"programs": [_record("ba-speedbird", monitor.STATUS_OPEN)]}
    records = [_record("ba-speedbird", monitor.STATUS_OPEN)]
    assert monitor.diff_transitions(records, previous) == []


def test_first_run_open_is_alerted_once():
    records = [_record("jet2-flightpath", monitor.STATUS_OPEN)]
    transitions = monitor.diff_transitions(records, previous=None)
    assert len(transitions) == 1
    assert transitions[0]["first_run"] is True


def test_interest_alerts_are_opt_in():
    previous = {"programs": [_record("tui-mpl", monitor.STATUS_CLOSED)]}
    records = [_record("tui-mpl", monitor.STATUS_INTEREST)]
    assert monitor.diff_transitions(records, previous) == []
    assert len(monitor.diff_transitions(records, previous, alert_on_interest=True)) == 1


def test_errors_never_alert():
    previous = {"programs": [_record("tui-mpl", monitor.STATUS_CLOSED)]}
    records = [_record("tui-mpl", monitor.STATUS_ERROR)]
    assert monitor.diff_transitions(records, previous) == []


# --------------------------------------------------------------------------------------
# End-to-end offline run
# --------------------------------------------------------------------------------------


def test_full_offline_run_writes_valid_status_json(tmp_path):
    output = tmp_path / "status.json"
    transitions = tmp_path / "transitions.json"

    exit_code = monitor.main(
        [
            "--targets",
            str(TARGETS),
            "--output",
            str(output),
            "--transitions-out",
            str(transitions),
            "--offline",
            "--fixtures-dir",
            str(FIXTURES),
        ]
    )
    assert exit_code == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema_version"] == monitor.SCHEMA_VERSION
    assert len(document["programs"]) == 7
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", document["generated_at"])
    assert set(document["summary"]) == {"open", "interest", "closed", "unknown", "error"}

    # Summary must agree with the rows (the widget trusts whichever it finds first).
    assert document["summary"] == monitor.build_summary(document["programs"])

    for record in document["programs"]:
        assert record["status"] in monitor.VALID_STATUSES
        assert record["passport_label"]
        assert record["apply_url"]
        assert record["evidence"]

    payload = json.loads(transitions.read_text(encoding="utf-8"))
    assert payload["schema_version"] == monitor.SCHEMA_VERSION
    triggered = {t["id"] for t in payload["transitions"]}
    # Air France and Wizz Air fixtures are OPEN, so a first run must alert on exactly those.
    assert triggered == {"airfrance-cadets", "wizzair-pilot-academy"}
    assert all(t["trigger"] == "open" for t in payload["transitions"])


def test_second_offline_run_is_idempotent(tmp_path):
    output = tmp_path / "status.json"
    transitions = tmp_path / "transitions.json"
    argv = [
        "--targets",
        str(TARGETS),
        "--output",
        str(output),
        "--transitions-out",
        str(transitions),
        "--offline",
        "--fixtures-dir",
        str(FIXTURES),
    ]
    assert monitor.main(argv) == 0
    first = json.loads(output.read_text(encoding="utf-8"))
    assert monitor.main(argv) == 0
    second = json.loads(output.read_text(encoding="utf-8"))

    # `checked_at` necessarily advances on every run, so idempotency is asserted on the
    # meaningful state: statuses, hashes and evidence must be byte-identical.
    stable = lambda doc: [
        (record["id"], record["status"], record["content_sha256"], record["evidence"])
        for record in doc["programs"]
    ]
    assert stable(first) == stable(second)
    # Nothing changed on the second run, so nothing may be alerted again.
    assert json.loads(transitions.read_text(encoding="utf-8"))["transitions"] == []
    assert second["summary"] == first["summary"]


def test_program_filter_keeps_other_rows(tmp_path):
    output = tmp_path / "status.json"
    transitions = tmp_path / "transitions.json"
    base = [
        "--targets",
        str(TARGETS),
        "--output",
        str(output),
        "--transitions-out",
        str(transitions),
        "--offline",
        "--fixtures-dir",
        str(FIXTURES),
    ]
    assert monitor.main(base) == 0
    assert monitor.main(base + ["--program", "tui-mpl"]) == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    assert len(document["programs"]) == 7
    ids = [record["id"] for record in document["programs"]]
    assert ids == EXPECTED_IDS


def test_invalid_config_is_rejected_loudly(tmp_path):
    bad = tmp_path / "targets.json"
    bad.write_text(
        json.dumps(
            {
                "programs": [
                    {
                        "id": "broken",
                        "airline": "Test",
                        "primary_url": "https://example.com/",
                        "rules": [{"status": "MAYBE", "match": "x"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(monitor.ConfigError):
        monitor.load_targets(bad)
