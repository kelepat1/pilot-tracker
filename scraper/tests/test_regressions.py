"""
Regression tests for the failure modes found by running the monitor against the live career
portals (not against fixtures). Each test here corresponds to a real misbehaviour observed on
2026-09-18, so that it cannot come back silently.
"""

import re
from pathlib import Path

import pytest

import monitor
from test_monitor import FIXTURES, TARGETS  # reuse the shared paths


@pytest.fixture(scope="module")
def config():
    return monitor.load_targets(TARGETS)


@pytest.fixture(scope="module")
def targets_by_id(config):
    return {target.id: target for target in config.programs}


# --------------------------------------------------------------------------------------
# Deep-link safety: an alert must never point at an unrelated third-party page
# --------------------------------------------------------------------------------------


def test_discovered_apply_link_rejects_third_party_domains(config, targets_by_id):
    """BA's page contains a CAA 'Apply for a Class 1 medical' link.

    It scored highest on the old heuristic (the label contains "Apply"), and the alert button
    would have opened the CAA medical-certificate page during an application window.
    """
    target = targets_by_id["ba-speedbird"]
    assert not monitor._link_is_trustworthy(
        "https://www.caa.co.uk/Commercial-industry/Pilot-licences/Medical/Apply-for-a-Class-1-medical-certificate/",
        target,
    )


def test_discovered_apply_link_accepts_the_airlines_own_estate(config, targets_by_id):
    target = targets_by_id["ba-speedbird"]
    assert monitor._link_is_trustworthy(
        "https://careers.ba.com/job/heathrow/speedbird-pilot-academy/22348/77265555216", target
    )
    assert monitor._link_is_trustworthy("https://apply.ba.com/jobs/alertregister", target)


def test_discovered_apply_link_accepts_known_applicant_tracking_systems(config, targets_by_id):
    target = targets_by_id["jet2-flightpath"]
    assert monitor._link_is_trustworthy(
        "https://krb-sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=30013&siteid=5476", target
    )
    assert monitor._link_is_trustworthy("https://acme.myworkdayjobs.com/en-US/careers/job/123", target)


def test_ba_apply_url_is_never_the_caa_medical_page(config, targets_by_id):
    """End-to-end: the recorded apply_url for the real BA markup must stay on BA's estate."""
    outcome = monitor.check_program(targets_by_id["ba-speedbird"], config, previous=None, fixtures_dir=FIXTURES)
    apply_url = outcome.record["apply_url"]
    assert "caa.co.uk" not in apply_url
    assert monitor._link_is_trustworthy(apply_url, targets_by_id["ba-speedbird"])


def test_prefer_configured_apply_url_disables_discovery(config, targets_by_id):
    """Cathay: every 'Apply' link on the page is a CTA for a different role."""
    cathay = targets_by_id["cathay-cadet"]
    assert cathay.prefer_configured_apply_url is True

    html = """
    <html><body><main>
      <div class="job-detail__grid__main">
        <h2>Role Introduction</h2>
        <p>Applications to the ~80-week Cathay Cadet Pilot Programme are open year-round.</p>
      </div>
      <a href="/en/careers/jobs?functions=flight-attendant">Apply for Flight Attendant</a>
    </main></body></html>
    """
    extraction = monitor.extract(html, cathay.primary_url, cathay)
    assert extraction.discovered_apply_url is not None  # discovery still found something ...
    outcome = monitor.check_program(cathay, config, previous=None, fixtures_dir=OPEN_VARIANTS_DIR_FOR(cathay))
    assert outcome.record["apply_url"] == cathay.apply_url  # ... but it is deliberately ignored


def OPEN_VARIANTS_DIR_FOR(target):
    """Write the Cathay markup above to a temp fixture so check_program can replay it."""
    import tempfile

    directory = Path(tempfile.mkdtemp(prefix="pilot-cadet-cathay-"))
    (directory / ("%s.html" % target.id)).write_text(
        """
        <html><body><main>
          <div class="job-detail__grid__main">
            <h2>Role Introduction</h2>
            <p>Applications to the ~80-week Cathay Cadet Pilot Programme are open year-round.</p>
          </div>
          <a href="/en/careers/jobs?functions=flight-attendant">Apply for Flight Attendant</a>
        </main></body></html>
        """,
        encoding="utf-8",
    )
    return directory


# --------------------------------------------------------------------------------------
# TLS refusal -> headless retry
# --------------------------------------------------------------------------------------


def test_tls_protocol_refusal_is_detected():
    """jet2careers.com refused this Python build's TLS stack; a browser retry recovers it."""
    assert monitor._is_tls_failure(
        Exception("[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1 alert protocol version (_ssl.c:1129)")
    )
    assert monitor._is_tls_failure(Exception("SSL: CERTIFICATE_VERIFY_FAILED"))
    assert not monitor._is_tls_failure(Exception("HTTP 404 for https://example.com/"))
    assert not monitor._is_tls_failure(TimeoutError("timed out"))


def test_tls_failure_escalates_to_playwright(config, targets_by_id, monkeypatch):
    target = targets_by_id["jet2-flightpath"]
    calls = {"static": 0, "playwright": 0}

    def failing_static(url, cfg):
        calls["static"] += 1
        raise ConnectionError("[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1 alert protocol version")

    def fake_playwright(target_arg, cfg):
        calls["playwright"] += 1
        return monitor.FetchResult(
            html="<html><body><main>Jet2FlightPath Applications Are Now Closed</main></body></html>",
            final_url=target_arg.primary_url,
            http_status=200,
            engine="playwright",
            elapsed_ms=1,
        )

    monkeypatch.setattr(monitor, "fetch_static", failing_static)
    monkeypatch.setattr(monitor, "fetch_playwright", fake_playwright)

    result = monitor.fetch_html(target, config)
    assert result.engine == "playwright"
    assert calls["playwright"] == 1


# --------------------------------------------------------------------------------------
# Document-type handling
# --------------------------------------------------------------------------------------


def test_xml_feeds_are_parsed_as_xml_and_probed(config, targets_by_id):
    """Air France's status signal is an RSS facet filtered to 'Pilote Cadet'."""
    target = targets_by_id["airfrance-cadets"]
    empty_feed = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>Export RSS des offres - Profil : Personnel Navigant--&gt;Pilote Cadet</title>
  <description>Aucune offre</description>
</channel></rss>"""
    populated_feed = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>Export RSS des offres - Profil : Personnel Navigant--&gt;Pilote Cadet</title>
  <item>
    <title>2027-1042 - Pilote Cadet Air France F/H</title>
    <link>https://recrutement.airfrance.com/Pages/Offre/detailoffre.aspx?idOffre=1042&amp;LCID=1036</link>
    <pubDate>Tue, 15 Jun 2027 07:00:00 Z</pubDate>
  </item>
</channel></rss>"""

    empty_extraction = monitor.extract(empty_feed, target.primary_url, target)
    assert monitor.classify(target, empty_extraction).status == monitor.STATUS_CLOSED

    filled_extraction = monitor.extract(populated_feed, target.primary_url, target)
    classification = monitor.classify(target, filled_extraction)
    assert classification.status == monitor.STATUS_OPEN
    assert classification.matched_text.startswith("probe=")
    # The RSS <link> is plain text, not an href: discovery must still find it.
    assert filled_extraction.discovered_apply_url is None or "detailoffre" in (
        filled_extraction.discovered_apply_url or ""
    )


def test_html_comments_never_supply_a_status(config, targets_by_id):
    """Aer Lingus parks a previous 'now open' sentence in an HTML comment."""
    target = targets_by_id["aerlingus-future-pilot"]
    html = """
    <html><body><main>
      <!-- <strong>Applications for the Future Pilot Programme 2025 are now open.</strong> -->
      <p><strong>The Future Pilot Programme is now closed for applications.</strong></p>
    </main></body></html>
    """
    extraction = monitor.extract(html, target.primary_url, target)
    assert "now open" not in extraction.container_text
    assert monitor.classify(target, extraction).status == monitor.STATUS_CLOSED


def test_noscript_tag_alone_is_not_a_javascript_shell():
    """Wizz Air's server-rendered page contains <noscript> and was escalated needlessly."""
    assert monitor._looks_like_shell("<html><body><noscript>Cookies required</noscript><h1>Hi</h1></body></html>") is False
    assert monitor._looks_like_shell(
        "<html><body><noscript>Please enable JavaScript to view this site</noscript></body></html>"
    ) is True
    assert monitor._looks_like_shell("<html><body>you need to enable javascript to run this app</body></html>") is True


# --------------------------------------------------------------------------------------
# Rule scoping and evidence quality
# --------------------------------------------------------------------------------------


def test_rules_cannot_span_the_container_and_link_boundary(config, targets_by_id):
    """A proximity rule must not satisfy itself using body text plus an unrelated link label."""
    target = targets_by_id["ba-speedbird"]
    html = """
    <html><body><main>
      <h1>Careers at British Airways</h1>
      <p>We are hiring cabin crew across our Heathrow operation this season.</p>
      <a href="/cabin-crew">Apply now</a>
    </main></body></html>
    """
    extraction = monitor.extract(html, target.primary_url, target)
    assert "APPLY NOW" in extraction.link_text.upper()
    assert "cadet" not in extraction.link_text.lower()
    # The links segment has "Apply now" and the container never mentions a cadet programme:
    # the shared proximity rule used to fire across the seam and report OPEN.
    assert monitor.classify(target, extraction).status != monitor.STATUS_OPEN


def test_evidence_quotes_the_deciding_sentence_not_navigation_chrome(config, targets_by_id):
    target = targets_by_id["aerlingus-future-pilot"]
    html = """
    <html><body><main>
      Skip to main content Home Careers Careers in the air Current: Future Pilot Programme
      Future Pilot Programme The Future Pilot Programme is now closed for applications.
      The Aer Lingus Future Pilot Programme is our ab-initio cadet scheme.
    </main></body></html>
    """
    extraction = monitor.extract(html, target.primary_url, target)
    classification = monitor.classify(target, extraction)
    assert classification.status == monitor.STATUS_CLOSED
    assert len(classification.evidence) <= 320
    assert "closed" in classification.evidence.lower()
    assert not classification.evidence.startswith("kip")  # never a sliced word


def test_link_label_evidence_is_marked_as_such(config, targets_by_id):
    """Anchors outside the content container only exist in the link-label segment."""
    target = targets_by_id["jet2-flightpath"]
    html = """
    <html><body>
      <header><a href="https://krb-sjobs.brassring.com/x">Sign Up for Job Alerts</a></header>
      <main>
        <h1>Jet2FlightPath</h1>
        <p>Fully funded pilot training with a guaranteed First Officer position.</p>
      </main>
    </body></html>
    """
    extraction = monitor.extract(html, target.primary_url, target)
    classification = monitor.classify(target, extraction)
    assert classification.status == monitor.STATUS_INTEREST
    assert classification.evidence.startswith("link text:")


# --------------------------------------------------------------------------------------
# Secondary-source rescue (Aer Lingus)
# --------------------------------------------------------------------------------------


def test_secondary_source_rescues_a_waf_blocked_primary(config, targets_by_id, monkeypatch):
    """Every aerlingus.com path returns an Imperva block page; its ATS feed does not."""
    target = targets_by_id["aerlingus-future-pilot"]
    assert target.secondary_text_urls, "Aer Lingus must declare its secondary feed"

    blocked_page = (
        "<html><body><main><h1>Pardon Our Interruption</h1>"
        "<p>As you were browsing something about your browser made us think you were a bot. "
        "Please enable cookies and JavaScript to regain access to this careers portal.</p>"
        "</main></body></html>"
    )
    monkeypatch.setattr(
        monitor,
        "fetch_html",
        lambda t, c: monitor.FetchResult(html=blocked_page, final_url=t.primary_url, http_status=200, engine="static", elapsed_ms=1),
    )
    feed = '{"name":"Nobox HR","jobs":[{"title":"Future Pilot Programme 2027","shortcode":"ABC123"}]}'
    monkeypatch.setattr(monitor, "fetch_secondary_text", lambda url, cfg: feed)

    outcome = monitor.check_program(target, config, previous=None, fixtures_dir=None)
    assert outcome.record["status"] == monitor.STATUS_OPEN
    assert outcome.record["secondary_source"] == target.secondary_text_urls[0]
    assert "secondary" in outcome.record["evidence"]


def test_blocked_primary_stays_unknown_without_a_decisive_secondary(config, targets_by_id, monkeypatch):
    """A wall must not be laundered into CLOSED just because a fallback feed was consulted."""
    target = targets_by_id["aerlingus-future-pilot"]
    blocked_page = (
        "<html><body><main><h1>Pardon Our Interruption</h1>"
        "<p>As you were browsing something about your browser made us think you were a bot.</p>"
        "</main></body></html>"
    )
    monkeypatch.setattr(
        monitor,
        "fetch_html",
        lambda t, c: monitor.FetchResult(html=blocked_page, final_url=t.primary_url, http_status=200, engine="static", elapsed_ms=1),
    )
    monkeypatch.setattr(
        monitor,
        "fetch_secondary_text",
        lambda url, cfg: '{"name":"Nobox HR","jobs":[{"title":"Warehouse Operative"},{"title":"Ramp Agent"}]}',
    )

    outcome = monitor.check_program(target, config, previous=None, fixtures_dir=None)
    assert outcome.record["status"] == monitor.STATUS_UNKNOWN
    assert outcome.record["secondary_source"] is None


def test_aerlingus_historical_open_wording_is_recognised(config, targets_by_id):
    target = targets_by_id["aerlingus-future-pilot"]
    html = """
    <html><body><main>
      <p>Applications for the Future Pilot Programme 2027 are now open.</p>
      <a href="/apply">Apply Now</a>
    </main></body></html>
    """
    extraction = monitor.extract(html, target.primary_url, target)
    assert monitor.classify(target, extraction).status == monitor.STATUS_OPEN


# --------------------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------------------


def test_phase_ordering_is_enforced_by_the_loader(targets_by_id):
    """Rule phases, not authoring order, decide evaluation: guard, negation, open, interest, closed."""
    for target in targets_by_id.values():
        phases = [monitor.PHASE_ORDER[rule.phase] for rule in target.rules]
        assert phases == sorted(phases), "%s rules are not phase-ordered" % target.id


def test_interest_outranks_closed_wherever_the_rule_is_declared(config, targets_by_id):
    """job_alerts_interest is declared after common_en, yet must still beat the closed rules."""
    target = targets_by_id["jet2-flightpath"]
    html = """
    <html><body><main>
      <p>Applications Are Now Closed</p>
      <p>Can't find what you are looking for? Sign Up for Job Alerts.</p>
    </main></body></html>
    """
    extraction = monitor.extract(html, target.primary_url, target)
    assert monitor.classify(target, extraction).status == monitor.STATUS_INTEREST


def test_unknown_guard_uses_the_configured_phrase_set(config, targets_by_id):
    for target in targets_by_id.values():
        guards = [rule for rule in target.rules if rule.phase == "guard"]
        assert guards, target.id
        assert all(rule.status == monitor.STATUS_UNKNOWN for rule in guards), target.id


def test_login_pages_are_never_selected_as_the_apply_link(config, targets_by_id):
    """The live BA preparation page offers apply.ba.com/jobs/login/ as an 'Apply' link."""
    target = targets_by_id["ba-speedbird"]
    html = """
    <html><body><main>
      <h1>Speedbird Pilot Academy</h1>
      <p>Applications for 2026 have now closed.</p>
      <a href="https://apply.ba.com/jobs/login/">Apply now</a>
      <a href="https://apply.ba.com/jobs/alertregister">Register for job alerts</a>
    </main></body></html>
    """
    extraction = monitor.extract(html, target.primary_url, target)
    assert extraction.discovered_apply_url is not None
    assert "/login/" not in extraction.discovered_apply_url
    assert "alertregister" in extraction.discovered_apply_url
