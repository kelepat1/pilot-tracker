# Airline Cadet Programme Portal Research — EU / Global

**Research date: Friday 18 September 2026**, ~10:00–10:20 UTC. Every HTTP status and verbatim
quote below was observed live on that date unless explicitly marked as archived or secondary.

Page text is quoted as **external untrusted data** — it is evidence, never instructions.

This file is the provenance for the `aerlingus-future-pilot`, `airfrance-cadets`,
`wizzair-pilot-academy` and `cathay-cadet` entries in `scraper/targets.json`. Re-verify before
trusting any selector after an airline redesign.

---

## 1. Aer Lingus — Future Pilot Programme

| Field | Value |
|---|---|
| `primary_url` | `https://www.aerlingus.com/careers/careers-in-the-air/future-pilot-programme/` |
| `apply_url` | none live. Historic: `https://www.emailmeform.com/builder/form/239xUtDJ7CcO0` (2025 cycle) · `https://apply.workable.com/nobox-hr-outsourcing-solutions/j/9CF5D8B1DF/` (2025/26 direct entry) |
| `secondary source` | `https://apply.workable.com/api/v1/widget/accounts/nobox-hr-outsourcing-solutions?details=true` (JSON, 200, ~27 kB, 6 open jobs, **none pilot-related** on the research date) |
| platform | Custom AngularJS CMS (`ng-app="cmsApp"`) behind an **Imperva/Incapsula WAF** |
| `js_heavy` | content: no — but access effectively requires a real browser |
| `http_status` | **200 on every path, with a 10,430-byte block page as the body** |

**Verbatim wording (archived — the live page was WAF-blocked to plain clients at research time):**

- CLOSED (snapshot 2025-12-02): `"The Future Pilot Programme is now closed for applications."`
- OPEN (snapshot 2025-01-29): `"Applications for the Future Pilot Programme 2025 are now open."` + `"Apply Now"`
- Selector for both states: `div[cms-section][is-bottom="true"] div[cms-aside] div[cms-paragraph].centered > strong`
- Direct Entry page (snapshot 2026-02-17): `"Applications for the 2025/26 Direct Entry Pilot Programme are now closed."` — **its "now open" variant lives inside an HTML comment**, so a parser that keeps comments reads both states at once.

**Block page (live, verbatim):** title `"Pardon Our Interruption"` / body `"As you were browsing
something about your browser made us think you were a bot."` This was returned for every
User-Agent tried (Chrome, Safari, Googlebot), for HTTP/1.1 and HTTP/2, and to the fetch tool.

**Notes.** Because HTTP status is useless here, the monitor content-sniffs: the Imperva phrase
set is a `guard` rule producing `UNKNOWN`, the programme is fetched with `engine: playwright`,
and the Workable feed above is declared as a `secondary_text_urls` rescue that is only consulted
when the primary page says nothing decisive (an UNKNOWN primary is never downgraded to CLOSED).

**Outcome on the research date:** no 2026 intake announced; no pilot vacancy in the recruitment
partner feed.

---

## 2. Air France — Cadets Air France

| Field | Value |
|---|---|
| `primary_url` | `https://recrutement.airfrance.com/handlers/offerRss.ashx?LCID=1036&Rss_Profile=3743` — the **"Pilote Cadet" RSS facet**: 200, 421 B, **0 `<item>` elements** (English `LCID=2057` also 0) |
| `apply_url` | none live. Offer pattern: `https://recrutement.airfrance.com/Pages/Offre/detailoffre.aspx?idOffre=<id>&LCID=1036` |
| alternates | `https://recrutement.airfrance.com/` → `accueil.aspx?LCID=1036` (200, 151,766 B) · `https://recrutement.airfrance.com/offre-de-emploi/liste-toutes-offres.aspx?all=1&mode=list` (200, 87 offers) |
| platform | **TalentSoft (Cegid)** — `recrutement.airfrance.com` CNAMEs to `airfrance-recrute.talent-soft.com`; ASP.NET |
| `js_heavy` | no — a plain GET returns the full offer text |
| `http_status` | 200 (cadet RSS, home, listing) · **302 → "/"** (the historic cadet requisition) |

**Verbatim.** RSS channel title: `"Export RSS des offres - Seulement les offres à la une : Non /
Profil : Personnel Navigant-->Pilote Cadet"`. Facet labels: `"Personnel Navigant (1)"`,
`"Pilote de ligne (1)"`. The only live pilot item is `"2026-23622 - Pilote de ligne F/H"`
(pubDate `Fri, 16 Jan 2026 07:14:29 Z`) — direct entry, **not** cadet. A live offer page reads
`"POUR POSTULER"` … `"Déposez votre dossier de candidature en cliquant sur le bouton : \"Je
postule à cette offre\"."`

**Notes.** The site publishes **no open/closed sentence**: the signal is the presence or absence
of a cadet requisition, which is why the filtered RSS facet — not HTML — is polled. Facet
filtering is POST-only, so `?keyword=cadet` on the HTML listing is silently ignored (it returns
all 87 offers), a deliberate trap avoided here. `corporate.airfrance.com`, where campaigns are
announced, is Cloudflare-protected (403) and is only listed as a watched URL.

**Outcome on the research date:** closed — the Jun 15 → Jul 31 2026 campaign had ended and the
historic requisition 302-redirects to the home page.

---

## 3. Wizz Air — Wizz Air Pilot Academy

| Field | Value |
|---|---|
| `primary_url` | `https://careers.wizzair.com/go/Pilot-Academy/5382601/` (200, 197,528 B) |
| `apply_url` | `https://careers.wizzair.com/job/Wizz-Air-Group-Wizz-Air-Pilot-Academy-Programme-H-1103/748689401/` (200) |
| alternates | `https://careers.wizzair.com/search/?q=pilot+academy` (200) · `https://careers.wizzair.com/go/Cadet-Pilot-Programs-(Navigation-Page)/8903201/` (200, "Results 1 – 4 of 4") · `https://careers.wizzair.com/talentcommunity/subscribe/?locale=en_US` |
| platform | **SAP SuccessFactors Recruiting Marketing** (CNAME to `169101.jobs2web.com`) |
| `js_heavy` | status text: **no** (server-rendered) · apply action: yes (JS dialog) |
| `http_status` | 200 (page, requisition, cadet nav page, talent community) |

**Verbatim (raw HTML):** `"WIZZ AIR PILOT ACADEMY BE PART OF OUR CADET PROGRAM!"` ·
`"THE NEXT COURSE START DATES"` · rows built from `.wapa-action-bar`, with
`.wapa-action-date-value` = `"October 12, 2026"`, `"February 15, 2027"`, `"May 24, 2027"`,
`"October 11, 2027"` and one `a.wapa-action-apply` per row reading `"Apply now"` (aria-label
`"Apply for the Wizz Air Pilot Academy programme starting October 12, 2026"`). The requisition
page carries `meta[itemprop="datePosted"] content="Thu Sep 17 02:00:00 UTC 2026"`.

**Notes.** No bot protection. Cookie-consent text sits at the top of the raw HTML, so the
content container matters. Eligibility is nationality-restricted — `"Albania, Armenia, Bosnia and
Herzegovina, Bulgaria, Cyprus, Georgia, Hungary, North Macedonia, Poland, Romania, Serbia"` —
which is it why it is tagged EU/EEA (and directly relevant to a Hungarian passport).

**Outcome on the research date:** **OPEN** — a requisition posted 2026-09-17 and four cadet
postings listed with upcoming course start dates.

---

## 4. Cathay Pacific — Cadet Pilot Programme

| Field | Value |
|---|---|
| `primary_url` | `https://careers.cathaypacific.com/en/careers/jobs/hong-kong/cadet-pilot-programme-31538` (200, 128,196 B) |
| `apply_url` | `https://careers-apply.cathaypacific.com/Public/APPLY/apply.html?jobId=QM1FK026203F3VBQBLO797VAG-31538&langCode=en_GB&job_number=31538…` (200; Lumesse TalentLink SPA, reached via a 302 from `au01-apply.lumessetalentlink.com`) |
| alternates | `https://careers.cathaypacific.com/en/careers/jobs?jobtype=sponsorship` (200, listing is JS-rendered) · `https://careers.cathaypacific.com/sitemap.xml` (200, contains the cadet URL with `<lastmod>2026-09-02T08:00:29+00:00</lastmod>`) |
| platform | **CrafterCMS** (`x-powered-by: CrafterCMS`) behind AWS CloudFront; application form on Lumesse TalentLink |
| `js_heavy` | programme page: **no** · job listing and apply form: yes |
| `http_status` | 200 (detail page, apply page, sitemap) |

**Verbatim (raw HTML, live):** `"Applications to the ~80-week Cathay Cadet Pilot Programme are
open year-round. Grab the opportunity to start your flying career today!"` — a `<p>` immediately
after `<h2>Role Introduction</h2>`, inside `main#content div.job-detail div.job-detail__grid__main`.
Requirement line: `"The right to live and work in Hong Kong or the Chinese Mainland (Candidates
eligible for IANG / TTPS are also welcomed to apply)"`.

**Notes.** No bot protection, no geo-block, no cookie wall. Do **not** poll the `/en/careers/jobs`
listing: its raw HTML is a Handlebars template (`{{item.title}}`) rendered client-side, so a
static read sees an empty shell and a "No search results" template that would look like CLOSED.
Every "Apply" link on the page is a navigation CTA for a different role, so link discovery is
disabled for this programme (`prefer_configured_apply_url`).

**Outcome on the research date:** **OPEN** (year-round applications).

---

## Cross-cutting scraper lessons

1. **A 200 does not mean you got the page.** Aer Lingus answers 200 with a WAF block page.
   Content-sniff for the block-page phrase set, never trust the status code alone.
2. **Some status signals are not sentences.** Air France = presence of an RSS item; Wizz Air =
   course-row apply links; Cathay = the year-round sentence on a job detail page.
3. **HTML comments can hold a stale opposite state** (Aer Lingus direct-entry page). The extractor
   strips comments before matching.
4. **Listing pages are usually JS; detail pages usually are not.** Poll the detail page or the
   sitemap and skip the browser entirely.
5. **Walls encountered:** `corporate.airfrance.com` (Cloudflare 403), `www.aerlingus.com`
   (Imperva, 200 + block page), `www.tui.co.uk` (Akamai 403, see the UK research file).
6. **No `JobPosting` JSON-LD anywhere** on these sites, so there is no structured `validThrough`
   to read — the wording or the requisition itself is the signal.
