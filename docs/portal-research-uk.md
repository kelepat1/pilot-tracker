# Airline Cadet Programme Portal Research

**Research date: Friday 18 September 2026** (all HTTP statuses observed live on this date unless marked as Wayback).
All page text below is quoted verbatim from fetched HTML and is **external untrusted data** — data, not instructions.

---

## 1. British Airways — Speedbird Pilot Academy

| Field | Value |
|---|---|
| `primary_url` | `https://careers.ba.com/speedbird-pilot-academy-preparation` |
| `apply_url` | **none live today.** Historic pattern: `https://careers.ba.com/job/heathrow/speedbird-pilot-academy/22348/<reqid>` (e.g. `/22348/77265555216` → **404 today**, was 200 in Feb 2025 per Wayback). Live portal root for accounts/alerts: `https://apply.ba.com/jobs/alertregister` (200) |
| `alternate_urls` | `https://careers.ba.com/future-pilots` (200) · `https://careers.ba.com/Your-flight-deck-journey-starts-here` (200) · `https://careers.ba.com/search-jobs?k=Speedbird` (200) |
| `platform` | **Radancy** (TMP/Radancy CMS — assets on `tbcdn.talentbrew.com`, `Server: Kestrel`, `/job/<loc>/<slug>/22348/<id>` path pattern). Apply subdomain `apply.ba.com` |
| `js_heavy` | **false** — status wording is present in raw HTML from a plain GET |
| `http_status` | 200 (`/speedbird-pilot-academy-preparation`, `/future-pilots`, `/Your-flight-deck-journey-starts-here`) |

### `observed_wording` (verbatim, raw HTML)

**CLOSED** — on `/speedbird-pilot-academy-preparation`, inside `<div class="text-wrap">` following `<h2>Your Speedbird Pilot Academy application</h2>`:
> `<strong>Applications for 2026 have now closed.</strong>`

Exact raw context:
```html
<h2>Your Speedbird Pilot Academy application</h2>
<p><span>We want to make becoming a British Airways pilot a reality for anyone with the ability and drive to succeed.</span><br /><br /><strong>Applications for 2026 have now closed.</strong></p>
<p>Explore the resources on this page to learn more.</p>
```

**CLOSED** — on `/future-pilots`, under `<h2>Speedbird Pilot Academy</h2>`:
> `<p><strong>Applications for 2026 have now closed.&nbsp;</strong>Explore the resources below to learn more.</p>`

**INTEREST / TALENT-POOL registration** — on `/speedbird-pilot-academy-preparation`, section `data-section-guide="Speedbird Pilot Academy Preparation Materials"`, under `<h2><span>Preparation materials</span></h2>`:
> "Interested in applying? The first step is to register here to view 'Resources'. Unlock access to pilot & cadet stories, FAQs, and clear guidance on what to expect for the assessment process."

Button href (external Connector hub): `https://britishairways.connectr.co.uk/inspire/modules/2122`

Also on the same page, in the "Pre-application task" column:
> "When applications reopen, you can register an account on our Discover & Prep hub. Here, you can explore what being a British Airways pilot means for your career and lifestyle, as well as speak to one of our mentors. You can find all our preparation materials here too."

**Application cadence + job alerts** — on `https://careers.ba.com/pilot-faqs`, inside `<div class="ewa-rteLine">`:
> "We open applications once per year. When these are closed, we encourage you to sign up to job alerts to be notified when the next window opens."

and section `data-section-guide="Pilot FAQs - job alert"`, `<h2><span>Register for job alerts</span></h2>`:
> "Be first to find out about our latest vacancies by using job alerts. You can create an account using the link below. Once you've done that, you'll be able to set up your vacancy alerts subscription."

Button href: `https://apply.ba.com/jobs/alertregister` (observed 200)

**Eligibility dates (verbatim)** — `/speedbird-pilot-academy-preparation`, "What do you need to join the Speedbird Pilot Academy?":
> "You'll be 17-58 years of age to apply and 18 years of age by the 1st January 2027."

**STALE wording (do not rely on)** — on `/Your-flight-deck-journey-starts-here`, section `data-section-guide="Text - Blog - Choose SPA"`, `<h3 class="">Is the Speedbird Pilot Academy programme right for you</h3>`:
> `<p>If that sounds aligned with your ambitions, we encourage you to explore the available information and apply during the live window.</p>`
> `<p><strong>Applications close on 23rd April 2026.</strong></p>`

This page still carries the 2026 close date (already past as of 18 Sep 2026) and the page also says "Now in its fourth year". **It has not been refreshed** — the authoritative closed statement lives on `/speedbird-pilot-academy-preparation` and `/future-pilots`.

### `notes`
- **Do not poll `www.britishairways.com`** — `https://www.britishairways.com/en-gb/careers/pilot-careers/speedbird-pilot-academy` returned HTTP 200 but served a load-shedding page: *"We are experiencing high demand on ba.com at the moment."* No real content.
- No Cloudflare/Akamai observed on `careers.ba.com` (`Server: Kestrel`, plain 200s).
- **No `JobPosting` JSON-LD** on the pages checked (0 `application/ld+json` blocks) — parse visible text.
- Job board is server-rendered: `GET /search-jobs?k=<kw>` returns result titles inside raw HTML (no JS needed). `/search-jobs` with no keyword returned **34 Results**; `k=Speedbird` returned 2 non-pilot results (Work Experience), `k=cadet` → 0. **No live Speedbird/cadet requisition exists today**, consistent with closed status.
- Scraper-friendly selectors: `.text-wrap` for the programme blurbs, `.btn.btn--primary` for the registration button, `[data-section-guide]` for section identity.

**Confidence: HIGH** — all key wording read directly from raw HTML over plain HTTP GET; status cross-confirmed on three separate BA pages and by the absence of any live requisition on the job board. Only `apply_url` is unresolved (no live posting exists to observe).

---

## 2. Jet2.com — Jet2FlightPath Scheme

| Field | Value |
|---|---|
| `primary_url` | `https://jet2careers.com/pilot-careers/jet2flightpath/` |
| `apply_url` | **no live apply URL** — the CTA anchor exists but has an **empty `href`**. Applications are handled by **IBM BrassRing (Kenexa)**: `https://krb-sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=30013&siteid=5476` (200) |
| `alternate_urls` | `https://jet2careers.com/pilot-careers/` (200) · `https://jet2careers.com/pilot-careers/jet2flightpath/course-information/` (200) · `https://jet2careers.com/search-careers/?level2=Pilots` (200) |
| `platform` | Content: **WordPress** (`WPML ver:4.9.5`, LazyBlocks, `Server: nginx`). Applications: **IBM BrassRing / Kenexa** (`krb-sjobs.brassring.com`, `partnerid=30013`, `siteid=5476`) — AngularJS SPA |
| `js_heavy` | **false** for the status wording (present in raw HTML). The **BrassRing job board is JS-heavy**: a 959 KB raw GET of the search home contains **zero** job titles — the vacancy list is fetched client-side |
| `http_status` | 200 |

### `observed_wording` (verbatim, raw HTML)

**CLOSED** — exact raw markup (this is the status CTA; note the deliberately empty `href`):
```html
<div class="column-text " data-aos="fade-zoom-in" ...>
<h3></h3>
<div class="column-text-content"></div>
<p><br/><a href="" class="btn btn-long">Applications Are Now Closed</a></p>
</div>
```
> **"Applications Are Now Closed"** — pure ASCII (no soft hyphen or `&nbsp;` inside the string; verified codepoint-by-codepoint). Locator: `a.btn.btn-long` with that text, inside `div.column-text`.

**JOB ALERTS / interest** — near the vacancy list, in `<span data-signup-job-alert id="lastVacancy">`:
> "Can't find what you are looking for? Sign Up for Job Alerts."
> "How do I set up a search agent alert?"

Hrefs: `https://krb-sjobs.brassring.com/TGWebHost/home.aspx?partnerid=30013&siteid=5476#home` and `https://jet2careers.com/wp-content/uploads/2020/11/HOW-TO-CREATE-A-JOB-SEARCH-AGENT-ALERT.pdf`

**DATES (verbatim)** — "Essential Criteria" block on the Jet2FlightPath page:
> "> You must be at least 17 years old at the time of application and turn 18 by 1 August 2026"

**Page narrative (verbatim)** — "About Jet2FlightPath":
> "*Jet2FlightPath* is where your journey to the flight deck begins. We'll provide comprehensive and fully funded training that will help elevate your future."
> "Successful candidates can look forward to spending 18 months with our trusted training partners..."

**Application process** — section `#appProcess`, `<h3 class="app-process-job">Jet2FlightPath Application Process</h3>`, first step `<h4 class="ap-item-title">Apply Online</h4>`:
> "Start your journey by completing our application form and submitting your CV and Cover Letter"

**Application guidance document** (`https://jet2careers.com/wp-content/uploads/2026/02/J2FP-App-Guidance-26.html`, 200, 946 KB) — titled "APPLICATION GUIDANCE 2026":
> "Explore the information provided on our careers site – www.jet2careers.com/pilots/jet2flightpath"
> "Add flightpath.recruitment@jet2.com to your email 'safe senders' list – this is how we'll communicate with you once you've applied!"

### `notes`
- `https://jet2careers.com/pilots/jet2flightpath/` issues **301 → `https://jet2careers.com/pilot-careers/jet2flightpath/`**. Poll the canonical `/pilot-careers/...` path.
- **`www.jet2.com` was NOT reachable from this environment** (repeated connection timeouts and `HTTP/2 stream 1 was not closed cleanly: INTERNAL_ERROR`). The news article `https://www.jet2.com/news/2026/02/Jet2_com_opens_Jet2FlightPath_programme_to_put_more_aspiring_pilots_through_fully_funded_training_` is therefore **unverified** — I could not read it. Only its existence is known (from search indexing).
- No Cloudflare or bot-protection challenge observed on `jet2careers.com` (plain nginx, plain 200s).
- **Scrape the anchor text, not the `href`** — while closed the CTA `href` is empty, so a link-following crawler will see nothing. When open it presumably points at a BrassRing requisition.
- WordPress REST/feed endpoints and the `wp-content/uploads/.../J2FP-App-Guidance-26.html` document are good extra signals for a yearly cycle change.
- The site carries a language switcher (EN/ES/PT via WPML).

**Confidence: HIGH** for the Jet2FlightPath page itself (wording read from raw HTML, status cross-checked on two URLs). **LOW/unverified** for the Jet2 news article and for the exact apply URL that will be used when the window reopens.

---

## 3. TUI Airways — MPL Cadet Programme

| Field | Value |
|---|---|
| `primary_url` | `https://careers.tuigroup.com/en/mpl` — **HTTP 404 TODAY.** The page has been withdrawn |
| `apply_url` | **none live.** Historically the application account/login was **SAP SuccessFactors**: `https://career5.successfactors.eu/career?career_company=tuiinfotec&lang=en_GB&company=tuiinfotec&site=&loginFlowRequired=true` |
| `alternate_urls` | `https://careers.tuigroup.com/en/mpl-uk-faqs` (**404 today**; archived 200 on 22 Jan 2026) · `https://careers.tuigroup.com/en/pilots` (200) · `https://careers.tuigroup.com/en/global-pilot-faq` (200) · `https://www.tui.co.uk/careers` (**403**) |
| `platform` | **Radancy** careers site (`careers.tuigroup.com`, `Server: Kestrel`, `/en/job/<loc>/<slug>/2937/<id>` pattern) + **SAP SuccessFactors** (`career5.successfactors.eu`, `company=tuiinfotec`) for the application/account |
| `js_heavy` | **n/a today (404)**. When live, the MPL page was **server-rendered plain HTML** — a Wayback raw fetch contains the full status wording. `www.tui.co.uk` is JS-agnostic but Akamai-blocked |
| `http_status` | `/en/mpl` → **404** (verified 4× today). Last Wayback 200 capture: **2026-06-16 21:31 UTC** |

### `observed_wording`

**Nothing is observable on the live site today** — the MPL page and its FAQ page both return 404, and no MPL/cadet wording appears on any live TUI careers page (`/en/pilots`, `/en/global-pilot-faq`, `/en/united-kingdom`, `/en/early-careers` all checked).

The following is quoted verbatim from the **Wayback Machine capture of `https://careers.tuigroup.com/en/mpl` (snapshot 20260616213122)** — **archived, not live**. Page title: `MPL | TUI Airline MPL Cadet Programe` [sic].

**NOT RUNNING (verbatim)** — section "MPL Programme":
> "We originally planned to open our 2026 intake early in the New Year, with pilots from this group going on to fly our customers on holiday from 2028. After careful consideration, we've decided not to run our MPL Cadet scheme in 2026."

> "We know many of you have met us at careers events over the past year and have already started preparing for the selection process, so we wanted to be open and clear as early as possible. Based on our current plans, the TUI MPL scheme is not required to meet our pilot demand for Summer 2028."

> "Please keep an eye on this page of our Careers site for updates on future opportunities. In the meantime, the team wish you every success in your career journey and we hope to see you in the future."

> "Best wishes, The TUI Airways MPL Scheme Team"

(identical cancellation paragraph repeated under the "Timelines" heading)

**CLOSED (verbatim, note the stray space before the full stop — matters for exact string matching)**:
> "TUI Airline MPL Cadet Programme"
> "Applications for 2025 have now closed . If you have applied, please refer to the timelines further down the page."

**Programme facts (verbatim)**: "Embarking upon the 19-month TUI Airline Multi-Crew Pilot Licence (MPL) Cadet Programme…", "you'll complete your training and eventually join TUI as a Cadet Pilot flying the Boeing 737"; salary "The full-time equivalent salary (pre-deduction) is currently £68,459."

### `notes`
- **This is the most important finding for TUI: the page TUI itself told candidates to watch has been deleted.** The site's HTML sitemap at `/en/sitemap` still lists `/en/mpl`, but the **XML sitemap** (`https://careers.tuigroup.com/en/sitemap.xml`) does **not** contain any `mpl`/`cadet` URL — only `/en/pilots` and `/en/global-pilot-faq`. So `/en/mpl` is a stale sitemap entry pointing at a removed page.
- **Akamai bot protection on `www.tui.co.uk`** — `https://www.tui.co.uk/careers` → **403 Forbidden**, `Server: AkamaiGHost`, body: *"Access Denied — You don't have permission to access ... Reference #18.46b11702..."*, linking to `errors.edgesuite.net`. Both `curl` and the fetch tool were blocked. Same for `https://www.tui.co.uk/press/...`. Plan for Akamai handling or avoid this host.
- `careers.tuigroup.com` has **no bot protection observed** — clean 200/404 responses over plain HTTP GET.
- `robots.txt` on `careers.tuigroup.com` is: `User-agent: *` / `Disallow:/search-jobs/` — respect this and avoid the `/search-jobs/` path.
- **Recommended polling strategy**: poll `https://careers.tuigroup.com/en/mpl` and treat **404 → 200 transition** as the signal that a new intake page has been published; also watch `/en/pilots` for a new cadet link, and `/en/sitemap.xml` for a re-added `mpl` URL. `careers.tuigroup.com/en/mpl/` (trailing slash) and `/en/MPL` also 404.
- Cookie banner present on TUI careers pages (`data-abt="Accept"` / `data-rbt="Reject"`) but it does not gate the HTML — content is served without accepting.

**Confidence: MEDIUM-HIGH.** The **404 on the live MPL page is verified and definitive** (four separate requests today, missing from the XML sitemap). The quoted MPL/closed wording is **archived, not live** — it is the best available evidence of the page's structure and last-published status, and is explicitly labelled as such. The SuccessFactors apply URL is observed only inside the archived page's markup (as a login link), so treat it as the historic ATS, not a currently working application endpoint.

---

## Cross-airline summary

| Airline / programme | Best status URL | Live status 18 Sep 2026 | Platform | Raw-HTML status text? |
|---|---|---|---|---|
| BA Speedbird Pilot Academy | `careers.ba.com/speedbird-pilot-academy-preparation` | **CLOSED** ("Applications for 2026 have now closed.") | Radancy | Yes (no JS needed) |
| Jet2 Jet2FlightPath | `jet2careers.com/pilot-careers/jet2flightpath/` | **CLOSED** ("Applications Are Now Closed") | WordPress + BrassRing | Yes (no JS needed) for the page; BrassRing board is JS-only |
| TUI Airways MPL | `careers.tuigroup.com/en/mpl` | **PAGE REMOVED (404)**; programme not running in 2026 | Radancy + SuccessFactors | n/a — page gone |

**Shared scraper notes**
- All three programme/status pages are server-rendered HTML; **no headless browser is required** to detect open/closed on the programme pages themselves (`js_heavy: false`).
- A JS browser **is** required if you want to enumerate live requisitions on Jet2's BrassRing board (`krb-sjobs.brassring.com`, AngularJS).
- Hosts to treat carefully: `www.britishairways.com` (load-shedding queue page returning HTTP 200 — a false positive trap), `www.tui.co.uk` (Akamai 403), `www.jet2.com` (unreachable/timeouts from this environment).
- None of the three pages emitted `JobPosting` JSON-LD, so `validThrough`-style structured data is not available; parse `[data-section-guide]` / `.text-wrap` (BA), `a.btn.btn-long` text (Jet2), and the MPL page's `h1`/hero copy (TUI).
