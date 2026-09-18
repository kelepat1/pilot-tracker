# Pilot Cadet Tracker

Passive, zero-cost, serverless monitoring for **fully funded airline pilot cadet programmes**,
with a native **macOS desktop widget** and **high-priority mobile alerts**.

Seven airline career portals are checked once a day by a GitHub Actions cron (`0 8 * * *`,
08:00 UTC). Nothing runs on your computer. When a programme transitions to `OPEN`, the run
pushes a Telegram message and an urgent email with the direct apply link, commits the new
`status.json`, and republishes it to GitHub Pages — which is what the macOS widget reads.

```text
pilot-tracker/
├── .github/workflows/
│   ├── daily_check.yml                 # cron: scrape → classify → alert → commit → publish
│   └── widget_build.yml                # real xcodebuild of the widget on a macOS runner
├── scraper/
│   ├── monitor.py                      # fetching, extraction, hashing, rule engine, state merge
│   ├── notifier.py                     # Telegram + Resend/SMTP alert dispatch (failure-safe)
│   ├── targets.json                    # the 7 programmes: URLs, selectors, passport tags, rules
│   ├── requirements.txt
│   ├── fixtures/                       # offline HTML replays (incl. an OPEN-window variant set)
│   └── tests/                          # 67 offline tests, no network needed
├── mac-widget/
│   ├── PilotCadetWidget.xcodeproj/      # ready-to-open project: host app + widget extension
│   ├── PilotCadetWidget.swift           # WidgetKit widget + TimelineProvider (medium & large)
│   ├── Models.swift                     # Decodable models matching status.json
│   ├── WidgetConfig.swift               # endpoint, App Group, refresh schedule, cache
│   ├── StatusViews.swift                # shared status/passport pills (both targets)
│   ├── PilotCadetApp.swift              # minimal host app: set the URL, refresh the widget
│   ├── Info.plist                       # widget extension Info.plist
│   ├── *.entitlements                   # App Sandbox + network + App Group
│   └── verify-build.sh                  # build verification (Xcode, or CLT-only fallback)
├── docs/
│   ├── portal-research-uk.md            # verbatim evidence: BA, Jet2, TUI (2026-09-18)
│   └── portal-research-eu.md            # verbatim evidence: Aer Lingus, Air France, Wizz, Cathay
├── status.json                          # the published state file (committed by CI)
└── README.md
```

---

## 1. What is monitored

| Airline | Programme | Passport tag | Right to work |
|---|---|---|---|
| British Airways | Speedbird Pilot Academy | 🇬🇧 UK | UK Right to Work |
| Jet2.com | Jet2FlightPath Scheme | 🇬🇧 UK | UK Right to Work |
| TUI Airways | MPL Cadet Programme | 🇬🇧 UK | UK Right to Work |
| Aer Lingus | Future Pilot Programme | 🇪🇺 EU | EU/EEA Right to Work |
| Air France | Cadets Air France | 🇪🇺 EU | EU/EEA Right to Work |
| Wizz Air | Wizz Air Pilot Academy | 🇪🇺 EU | EU/EEA Right to Work |
| Cathay Pacific | Cadet Pilot Programme | 🌍 Global | International / Targeted RTW |

Every URL, selector and rule in this table lives in `scraper/targets.json` — nothing is hard-coded
in Python, so a portal redesign is a config edit, not a code change.

### Status semantics (this is the core design decision)

| Status | Meaning | Widget |
|---|---|---|
| `OPEN` | Applications are being accepted **right now**. This is the only state that triggers an alert. | 🟢 green |
| `INTEREST` | The window is shut, **but the airline offers a programme-specific route to be notified** (talent pool, job alerts, prep-hub registration). There is something useful to do today. | 🟠 orange |
| `CLOSED` | No window and no notification route. Nothing actionable. | ⚪️ gray |
| `UNKNOWN` | The page was reachable but said nothing decisive — bot wall, load-shedding page, redesign. Surfaced on the desktop so a blind scraper is *visible* instead of silently reported as closed. | ⚪️ gray |
| `ERROR` | The check failed outright. The last known status is kept and the row is flagged stale (`consecutive_failures`). | ⚫️/red |

`INTEREST` deliberately outranks `CLOSED`: "applications are now closed — register your interest"
is an actionable state, and *"keep an eye on this page"* is deliberately **not** treated as
`INTEREST`, because it offers no route and this monitor exists to do the watching.

---

## 2. Quick start (about 15 minutes)

> Full walkthrough with every click, the token-vs-password subtlety and a troubleshooting
> table: **[`docs/github-setup.md`](docs/github-setup.md)**.

### Step 1 — push the repository

```bash
cd pilot-tracker
git init -b main
git add .
git commit -m "feat: pilot cadet monitor"
gh repo create pilot-tracker --public --source=. --push   # or: git remote add origin … && git push -u origin main
```

The repository **must be public** if you want free GitHub Pages hosting and a widget that can
read the feed without a token. It contains no personal data — only public airline status wording.

### Step 2 — enable Pages and write permission

1. **Settings → Actions → General → Workflow permissions** → *Read and write permissions*.
   Without this the job cannot commit `status.json` back.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
   The `publish` job deploys `status.json` plus a small status page to
   `https://<username>.github.io/pilot-tracker/`.

### Step 3 — add the alert secrets

**Settings → Secrets and variables → Actions → New repository secret.** All are optional: a
channel with missing credentials is reported as `skipped`, never as a failure, and the monitor
still commits and publishes.

| Secret | Required for | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram push | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Telegram push | Your chat id; comma-separate several ids |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram push | Optional, for forum topics |
| `EMAIL_API_KEY` | Email via Resend | `re_…`; takes priority over SMTP |
| `EMAIL_FROM` | Email | A verified Resend sender, e.g. `alerts@yourdomain.com` |
| `EMAIL_TO` | Email | Comma-separated recipients |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_SECURITY` | Email via SMTP | Fallback when `EMAIL_API_KEY` is absent; `SMTP_SECURITY` is `starttls` (default), `ssl` or `none` |

Telegram message format: MarkdownV2, escaped correctly, with an inline **Apply now →** link. If
Telegram rejects the Markdown (HTTP 400), the notifier automatically resends as plain text rather
than losing the alert.

### Step 4 — run it once

**Actions → Daily pilot cadet check → Run workflow.** Tick `dry_run` first if you want to see the
payloads without sending anything and without committing. Then open
`https://<username>.github.io/pilot-tracker/status.json`.

### Step 5 — build the widget

```bash
open mac-widget/PilotCadetWidget.xcodeproj
```

1. Select the **PilotCadet** target → *Signing & Capabilities* → choose your **Team**.
2. Set a unique bundle id for both targets (e.g. `com.yourname.PilotCadet` and
   `com.yourname.PilotCadet.PilotCadetWidget`).
3. Add the **App Groups** capability to **both** targets with the group
   `group.com.example.pilotcadet`, and keep `WidgetConfig.appGroupIdentifier` in sync.
   It is what lets the widget read the last-known-good cache.
4. Edit `WidgetConfig.defaultStatusURL` to your Pages URL (or paste it into the running app — the
   app saves it into the shared defaults, which the widget reads first).
5. Run the **PilotCadet** scheme (⌘R), then add the widget: **System Settings → Desktop & Dock →
   Widgets → Edit Widgets**, or right-click the desktop → *Edit Widgets* → search "Pilot Cadet
   Watch". `systemMedium` and `systemLarge` are supported.

Deployment target is **macOS 14.0**, so Sonoma and Sequoia are both fine.

If Xcode is not installed yet (`xcode-select -p` printing `/Library/Developer/CommandLineTools`
means only the Command Line Tools are present), install it from the App Store — it needs your
Apple ID, so this step cannot be automated — then point the toolchain at it and re-verify:

```bash
sudo xcode-select -s /Applications/Xcode.app   # switch from CLT to the full toolchain
sudo xcodebuild -license accept                # required once
xcodebuild -runFirstLaunch                     # installs the extra components
cd mac-widget && ./verify-build.sh             # now runs a real xcodebuild
```

> **No Xcode project needed.** The `.xcodeproj` is provided for convenience, but `Models.swift`,
> `WidgetConfig.swift`, `StatusViews.swift` and `PilotCadetWidget.swift` are plain source files: if
> you prefer, create a new macOS app + Widget Extension in Xcode and drag them in, adding
> `Models/WidgetConfig/StatusViews` to both targets. `PilotCadetWidget.swift` owns the widget's
> `@main` entry point and must belong to the extension only; `PilotCadetApp.swift` is the app's
> `@main` and belongs to the app only.

---

## 3. How it works

### Extraction (`scraper/monitor.py`)

1. **Fast path** — `httpx` GET with a descriptive User-Agent, redirects followed, one request per
   URL, 2.5 s politeness delay between programmes.
2. **Automatic escalation** — the page is escalated to headless Chromium (`playwright`) when it is
   bot-walled, when it is a genuine "JavaScript required" shell, when the rendered text is thinner
   than `min_text_chars`, or when the TLS handshake itself is refused (see Jet2 below).
   Programmes whose portal is known to be client-rendered set `"engine": "playwright"` outright.
3. **Content container** — the first matching selector from `content_selectors` (CSS *or* XPath)
   that yields real text. `<script>`, `<style>`, `<noscript>`, `<template>`, `<svg>`, `<iframe>`
   and `<form>` are removed, **and so are HTML comments** — airlines park a stale opposite state
   inside them.
4. **Scrubbing and hashing** — timestamps, nonces, session ids, CSRF tokens, cache-busting query
   strings, asset fingerprints, "3 minutes ago" counters, visitor counts and copyright years are
   replaced with placeholders, then the normalised container is SHA-256 hashed. Change detection
   is driven by that hash, which is what keeps tracking tokens from causing false positives. In
   CI a full run produces zero diffs when nothing happened.
5. **Rule engine** — ordered, first-match-wins, evaluated in **phases**, which is the part that
   makes the catalogue safe to edit:

   | Phase | Purpose |
   |---|---|
   | `guard` | bot walls, load-shedding and maintenance pages → `UNKNOWN` |
   | `negation` | "not currently open" — contains the word *open*, so it must run before `open` |
   | `open` | "applications are now open", "now accepting applications", live-requisition DOM probes |
   | `interest` | "register your interest", job alerts, talent community |
   | `closed` | "applications are now closed", "no current vacancies" |

   Rules match the content container and the link-label list **separately**, so a proximity rule
   such as *"apply now within 160 characters of a cadet keyword"* cannot satisfy itself using body
   text plus an unrelated navigation link.
6. **State merge** — `status.json` is read back so `changed_at`, `content_changed` and
   `consecutive_failures` survive across runs. A failed check keeps the last known status and
   marks the row stale instead of pretending the window closed.

### Alerting (`scraper/notifier.py`)

Only transitions **into** `OPEN` alert (first-run `OPEN` too, so setup is not silent).
`--alert-on-interest` and `--alert-on-closed` opt in to the others. Every channel is wrapped so
that a failure can never prevent the status commit: a missed application window is the only
outcome that actually matters.

### Publishing

`status.json` is the contract between the cloud and the widget. Schema (abridged):

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-18T10:24:02Z",
  "summary": { "open": 2, "interest": 2, "closed": 3, "unknown": 0, "error": 0 },
  "programs": [
    {
      "id": "cathay-cadet",
      "airline": "Cathay Pacific",
      "program": "Cadet Pilot Programme",
      "passport": "Global",
      "passport_label": "🌍 Global",
      "rtw_scope": "International / Targeted RTW",
      "status": "OPEN",
      "previous_status": "CLOSED",
      "status_changed": true,
      "changed_at": "2026-09-18T10:24:02Z",
      "checked_at": "2026-09-18T10:24:02Z",
      "content_changed": false,
      "content_sha256": "…",
      "source_url": "…",
      "apply_url": "…",
      "engine": "static",
      "http_status": 200,
      "evidence": "Applications to the ~80-week Cathay Cadet Pilot Programme are open year-round.",
      "matched_rule": "rules[7]",
      "consecutive_failures": 0,
      "error": null
    }
  ]
}
```

`evidence` always quotes the wording that decided the status, so a human can verify the call in
one click. `apply_url` is only replaced by a discovered link when that link is on the airline's own
estate or a known applicant-tracking system — see the safety note below.

### The widget (`mac-widget/`)

`URLSession` fetch → `JSONDecoder` → one row per programme, sorted `OPEN` → `INTEREST` →
`UNKNOWN` → `ERROR` → `CLOSED`. Each row is a `Link` to `apply_url`, so clicking opens the exact
application page; the whole widget also carries a `widgetURL` pointing at the highest-priority
row. `Timeline(entries:policy:.after(next 08:10 UTC))`, retrying 30 minutes after a failure. The
last successful payload is cached in the App Group, so a network hiccup shows stale data with a
warning instead of an empty widget. Decoding is defensive: an unknown status string or a missing
field degrades one row, never the whole widget.

macOS decides exactly when a widget refreshes, so treat the widget as "at most daily" — the push
alert is the time-critical channel.

The widget degrades in order of freshness rather than failing: live feed → last successful fetch
→ `mac-widget/BundledStatus.json` (a snapshot compiled into the extension, so a fresh install
shows the seven programmes instead of an error) → error panel showing the endpoint it tried. Keep
the snapshot current with `cp status.json mac-widget/BundledStatus.json` before a build; CI does
this automatically.

### Verifying the widget build

```bash
cd mac-widget
./verify-build.sh                 # full: xcodebuild + product checks (needs full Xcode)
./verify-build.sh --link-only     # compile+link+assemble+ad-hoc sign (Command Line Tools only)
./verify-build.sh --typecheck-only
python3 check-pbxproj.py          # static project-file check (no Xcode needed)
python3 check-contract.py         # status.json <-> Models.swift contract
```

**Verified against Xcode 27.0 (27A266a)** — `xcodebuild` builds both the host app and the widget
extension in Debug *and* Release, producing universal (x86_64 + arm64) binaries, with the
extension embedded at `PilotCadet.app/Contents/PlugIns/PilotCadetWidgetExtension.appex` and its
`Info.plist` correctly declaring `com.apple.widgetkit-extension` with `LSMinimumSystemVersion`
14.0.

`verify-build.sh` needs no sudo even when Xcode is installed but the system-wide developer
directory still points at the Command Line Tools: it detects `/Applications/Xcode.app` and builds
through `DEVELOPER_DIR` instead of changing your machine's selection. (Switching permanently is
one command — `sudo xcode-select -s /Applications/Xcode.app` — and is optional.) It also reports
the licence gate explicitly if Xcode is installed but `sudo xcodebuild -license accept` has not
been run yet.

`check-pbxproj.py` exists because Xcode's own error for a malformed project file is hard to read
back. It catches duplicate object IDs, dangling references, product wiring and extension
embedding without needing Xcode — the class of bug that a set-based integrity check silently
passes and only a real `xcodebuild` run exposes.

`--link-only` is a genuinely strong check that works without Xcode: it compiles **and links** both
targets for release, confirms the extension links `WidgetKit` and `SwiftUI`, assembles a real
`.app` with `PilotCadetWidgetExtension.appex` embedded, ad-hoc signs both bundles, runs
`codesign --verify --deep --strict`, and asserts that App Sandbox, network client and the App
Group entitlement are present in *both* products.

For a **working local widget**, an ad-hoc signed build is enough — verified on 2026-09-18 with
Xcode 27.0: build with `CODE_SIGN_IDENTITY="-"`, copy the `.app` to `/Applications`, run it, and
`pluginkit -m -p com.apple.widgetkit-extension` lists the extension, which is what the widget
gallery reads. An Apple ID/team is only needed to distribute the widget to other machines. The
exact command sequence is in `mac-widget/README.md`.

`verify-build.sh` picks its SDK with a real SwiftUI-using probe, because on this machine the
**default** SDK (`MacOSX.sdk` → `MacOSX27.0.sdk`) ships *without the SwiftUI macro plugin*, so
every `@State` / `@Environment` fails with `SwiftUIMacros.StateMacro could not be found`.
`MacOSX26.5.sdk` compiles it correctly and the probe finds it automatically. Installing Xcode and
selecting it (`sudo xcode-select -s /Applications/Xcode.app`) removes the problem, because Xcode
ships a matched toolchain and its own SDKs.

For a true `xcodebuild` verification without installing Xcode locally,
`.github/workflows/widget_build.yml` builds the project with a real Xcode toolchain on GitHub's
`macos-14` runners on every push touching `mac-widget/**`, verifies the extension is embedded and
declares `com.apple.widgetkit-extension`, and re-checks the `status.json` ↔ `Models.swift`
contract so the two halves cannot drift apart silently.

---

## 4. Verified status as of the last run

Produced by a real run of `scraper/monitor.py` on **2026-09-18**, against the live portals:

| Airline | Status | Why (evidence) | Path used |
|---|---|---|---|
| British Airways | `INTEREST` | "The first step is to register here to view 'Resources'." + job-alert registration | static |
| Jet2.com | `INTEREST` | "Sign Up for Job Alerts." (the CTA reads "Applications Are Now Closed") | Chromium (TLS retry) |
| TUI Airways | `CLOSED` | MPL page deleted → HTTP 404 mapped by config to CLOSED | static |
| Aer Lingus | `CLOSED` | "The Future Pilot Programme is now closed for applications." | Chromium through the WAF |
| Air France | `CLOSED` | "Pilote Cadet" RSS facet contained no cadet vacancy | static (RSS) |
| Wizz Air | `OPEN` | course-row apply links + a live Pilot Academy requisition | static |
| Cathay Pacific | `OPEN` | "Applications to the ~80-week Cathay Cadet Pilot Programme are open year-round." | static |

Per-portal evidence, verbatim wording and platform details:
`docs/portal-research-uk.md`, `docs/portal-research-eu.md`.

### Per-portal gotchas the code defends against

- **British Airways** — `www.britishairways.com` serves a *load-shedding* page with HTTP 200
  ("experiencing high demand"), which would look like a status change; it is never polled and the
  phrase set maps it to `UNKNOWN`. `/Your-flight-deck-journey-starts-here` is stale (it still
  advertised a window that had closed), so it is watched, not polled.
- **Jet2** — the status lives in an anchor *label* whose `href` is empty while the window is shut,
  so the anchor text is scraped, not the link. `jet2careers.com` also refuses this project's TLS
  stack (`TLSV1_ALERT_PROTOCOL_VERSION`), so the TLS failure triggers the Chromium retry instead of
  losing the programme.
- **TUI** — deleted the MPL page it told candidates to watch, so `404 → CLOSED` is an explicit
  config mapping, and the URL has **no fallback** on purpose (falling through to `/en/pilots` would
  mask the signal). `www.tui.co.uk` is Akamai-blocked (403) and is not polled.
- **Aer Lingus** — Imperva serves a 10 kB block page with HTTP **200**; the guard rule reports
  `UNKNOWN` when the wall wins, `engine: playwright` is used to try to get through, and a
  `secondary_text_urls` feed (the recruitment partner's JSON API) is consulted only when the
  primary says nothing decisive. An `UNKNOWN` primary is never downgraded to `CLOSED`.
- **Air France** — no open/closed sentence exists; the filtered RSS facet for the "Pilote Cadet"
  profile is polled and any `<item>` means a live campaign. `?keyword=` on the HTML listing is
  ignored server-side (POST-only facets), so it is not used.
- **Wizz Air** — the status text is server-rendered while the apply action is JavaScript; a
  `<noscript>` tag alone no longer triggers a browser escalation.
- **Cathay** — the `/en/careers/jobs` listing is a client-rendered Handlebars template whose
  "No search results" template text would read as CLOSED from a static fetch, so the server-rendered
  job-detail page and the sitemap are polled instead, and link discovery is disabled because every
  "Apply" link there belongs to a different role.
- **Deep links** — discovery once selected
  `https://www.caa.co.uk/…/Apply-for-a-Class-1-medical-certificate` for British Airways (it
  outscored everything on the "Apply" heuristic). Discovered links are now accepted only from the
  airline's own domain or a known ATS host, and Cathay prefers its configured deep link outright.

---

## 5. Running it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r scraper/requirements.txt
.venv/bin/python -m playwright install chromium          # only needed for the JS paths

# Offline: replay the checked-in fixtures, send nothing
.venv/bin/python scraper/monitor.py --offline --fixtures-dir scraper/fixtures \
    --output /tmp/status.json --transitions-out /tmp/transitions.json

# Live, one programme, alerts rendered but not sent
.venv/bin/python scraper/monitor.py --program tui-mpl \
    --transitions-out /tmp/transitions.json
.venv/bin/python scraper/notifier.py --transitions /tmp/transitions.json --dry-run

# Live, everything (this is what CI runs)
.venv/bin/python scraper/monitor.py --output status.json --transitions-out build/transitions.json
```

Useful flags: `--program <id>` (repeatable), `--engine static|playwright`, `--offline`,
`--alert-on-interest`, `--alert-on-closed`, `--fail-on-error`, `-v`.
Exit code is 0 even when individual portals fail (failure isolation is a feature); the workflow
fails only if **every** programme fails.

Tests — 67 of them, no network required:

```bash
.venv/bin/python -m pytest scraper/tests -q
```

`scraper/tests/test_regressions.py` is worth reading before editing anything: every test in it is a
real misbehaviour that was observed against a live portal, including the CAA medical link, the
comment-hidden Aer Lingus state, the cross-boundary proximity match and the `<noscript>` false
positive.

### Working in VS Code

The repo ships a `.vscode/` setup so the whole monitoring half of the project — and the parts of
the widget that can be compiled without Xcode — can be driven from VS Code:

| Piece | What it gives you |
|---|---|
| `.vscode/tasks.json` | 10 tasks (⇧⌘B / *Terminal → Run Task*): run the test suite, run the monitor offline or live, check a single programme (with a picker), dry-run the notifier, verify the widget build, validate the JSON contract |
| `.vscode/launch.json` | Debug configurations for `monitor.py` and `notifier.py`, offline or live |
| `.vscode/settings.json` | Python interpreter + pytest wiring, and `SDKROOT=MacOSX26.5.sdk` in the integrated terminal so Swift commands work on the SDK described above |
| `.vscode/extensions.json` | Recommends the Swift extension (it works without Xcode: the Command Line Tools already ship `sourcekit-lsp`), Python, YAML, GitHub Actions and ShellCheck |
| `mac-widget/Package.swift` | A SwiftPM view of the shared sources (`Models`, `WidgetConfig`, `StatusViews`) so the Swift extension has a real project to type-check: `SDKROOT=…/MacOSX26.5.sdk swift build` |
| `mac-widget/check-contract.py` | Asserts `status.json` and `Models.swift` still agree — the contract no compiler checks |

**What VS Code cannot do here:** it is an editor and bundles no compiler (verified — there is no
`swiftc` or `xcodebuild` inside the app), so it drives the *same* Command Line Tools this repo
already uses. It cannot install Xcode, and it cannot produce a WidgetKit extension that macOS will
load, because that needs Xcode's build system and a real signing identity.

---

## 6. Maintenance

- **A portal redesign broke a programme** → run it with `-v`, look at `evidence`,
  `container_selector` and `matched_rule` in `status.json`, then update that programme's
  `content_selectors` / `rules` in `targets.json`. If the page now says something it has never said
  before, you may see `UNKNOWN` — that is the design working: the widget shows that the monitor is
  blind rather than inventing a status.
- **Rules are additive and phase-ordered.** Add a negation with `"phase": "negation"`, or a shared
  phrase to a set in `rule_sets`; you never have to worry about where the rule sits in the file.
- **Adding a programme** = one object in `programs[]` (plus a fixture if you want it covered
  offline). `docs/*.md` is the place to record the wording you verified.
- **`status.json` changes every run**, because `checked_at` advances. That daily commit is
  intentional: GitHub disables scheduled workflows after 60 days of repository inactivity, and a
  daily heartbeat keeps the cron alive.

## 7. Scope, etiquette and limits

- Passive, unauthenticated daily reads of **public** career pages, once per programme per day, with
  a descriptive User-Agent and a politeness delay. No logins, no forms, no personal data, no
  scraping of anything behind a candidate account. Respect each site's terms and `robots.txt`;
  `careers.tuigroup.com` disallows only `/search-jobs/`, which is not polled.
- The monitor reports **what the page said**. Airline wording is sometimes stale, ambiguous or
  published late — always confirm on the portal before acting, which is what the evidence line and
  the deep link are for.
- Bot protection may block a programme entirely (today: Aer Lingus). The honest outcome is
  `UNKNOWN` plus a note in `consecutive_failures`/`error`, not a guess.
- Widget refresh timing is controlled by macOS, not by this project.
