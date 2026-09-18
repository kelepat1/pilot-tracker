# GitHub setup, step by step

Everything the monitor needs — the daily cron, the alerts, the published `status.json` the widget
reads — lives in a GitHub repository. This is the complete path from this folder to a running
system, with the exact commands for this Mac.

**Time:** about 15 minutes, most of it clicking in the GitHub UI.
**Prerequisites:** a GitHub account (free — [sign up](https://github.com/signup) if you need one).

---

## 1. Commit the repository locally

There is no git identity configured on this Mac, and commits must be attributed to someone, so set
one first. Use the email attached to your GitHub account — or, to keep it private, GitHub's
no-reply form `<your-user-id>+<username>@users.noreply.github.com` (find your id at
`https://api.github.com/users/<username>`).

```bash
cd "/Users/patrikk31/Pilot Program Notification App/pilot-tracker"

git config user.name  "Your Name"          # add --global to apply to all your repos
git config user.email "you@example.com"

git commit -m "feat: pilot cadet monitor, mobile alerts and macOS widget"
git log --oneline                          # should show one commit, ~42 files
```

<details>
<summary>What is in that commit</summary>

41 files: the scraper (`scraper/monitor.py`, `notifier.py`, `targets.json`, 68 tests, fixtures),
both workflows, the widget sources plus its Xcode project, the verification scripts, the research
evidence in `docs/`, and `status.json` with real data. Build output is excluded
(`.build/`, `build/`, `.swiftcache/`, `.swiftpm/`, `DerivedData/`).
</details>

---

## 2. Create the repository on GitHub

1. Go to **<https://github.com/new>**.
2. **Repository name:** `pilot-tracker`
   *The Pages URL becomes `https://<username>.github.io/pilot-tracker/status.json`. If you pick a
   different name, tell me — the widget's URL is compiled in and I'll change and rebuild it.*
3. **Visibility: Public.**
   Required for free GitHub Pages, and it is what lets the widget fetch the feed without a token.
   The repo holds only public airline status wording, fixtures and research notes — no personal
   data, and no credentials (secrets live in GitHub, never in the repo).
4. **Do NOT** initialise with a README, `.gitignore` or licence — you already have a commit and a
   `.gitignore`, and initialising creates a conflicting history you would have to merge.
5. Click **Create repository**. Leave the page open: it shows the push commands you need next.

---

## 3. Authenticate so you can push

GitHub stopped accepting account passwords for git operations in 2021, so you need either a
**personal access token** (easiest) or **SSH keys** (no expiry). Pick one.

### Option A — HTTPS with a personal access token (recommended)

1. Open <https://github.com/settings/tokens> → **Generate new token** → **Generate new token
   (classic)**.
   *Fine-grained tokens also work: give them **Contents: Read and write** on this repository.*
2. **Note:** `pilot-tracker push`
3. **Expiration:** 90 days is fine; calendar a reminder, because pushes start failing when it lapses.
4. **Scopes:** tick **`repo`** (a public repo only needs `public_repo`).
5. **Generate token**, then copy the `ghp_…` string — GitHub shows it **once**.

When you push, git asks for a *username* and a *password*:

| Prompt | What to enter |
|---|---|
| Username | your GitHub username |
| Password | **the token** (`ghp_…`), *not* your account password |

macOS will store it in your Keychain (`credential.helper=osxkeychain` is already configured on
this machine via Xcode), so it is asked once, not every push.

### Option B — SSH keys (no tokens, no expiry)

```bash
ssh-keygen -t ed25519 -C "you@example.com" -f ~/.ssh/id_ed25519   # this Mac has no keys yet
pbcopy < ~/.ssh/id_ed25519.pub        # copies the public key
```

Then GitHub → **Settings → SSH and GPG keys → New SSH key** → paste → **Add SSH key**. Verify:

```bash
ssh -T git@github.com                 # expect: "Hi <username>! You've successfully authenticated…"
```

With SSH, use the `git@github.com:<username>/pilot-tracker.git` remote in step 4.

### Option C — GitHub CLI

`gh` is not installed here and neither is Homebrew, so this route means installing both first:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install gh && gh auth login       # then: gh repo create pilot-tracker --public --source=. --push
```

---

## 4. Push

```bash
cd "/Users/patrikk31/Pilot Program Notification App/pilot-tracker"

git remote add origin https://github.com/<USERNAME>/pilot-tracker.git   # or git@github.com:<USERNAME>/…
git push -u origin main
```

Reload the repository page: 41 files, and the top commit is yours.

---

## 5. Let the workflow commit back (easy to miss)

**Settings → Actions → General → Workflow permissions → select “Read and write permissions” →
Save.**

The daily job commits the updated `status.json` back to the repository. Without this, that step
fails with `403` and the feed stops updating (the job itself still succeeds, which makes it easy to
miss — check the log of the *Commit status.json when it changed* step).

---

## 6. Enable GitHub Pages

**Settings → Pages → Build and deployment → Source: `GitHub Actions`.**

Do **not** choose "Deploy from a branch": the workflow uploads a Pages artifact and deploys it via
`actions/deploy-pages`. Selecting the branch mode instead leaves `status.json` unreachable.

The first deployment creates a `github-pages` environment automatically; if your organisation
requires approvals, approve the `publish` job when it runs.

---

## 7. Add the alert secrets

**Settings → Secrets and variables → Actions → New repository secret**, one at a time.

All of them are optional: a channel with missing credentials is reported as `skipped`, never as a
failure, and the monitor still commits and publishes — so you can add them later.

| Secret | Purpose |
|---|---|
| `EMAIL_API_KEY` | Resend API key (`re_…`) — takes priority over SMTP |
| `EMAIL_FROM` | A verified Resend sender (`alerts@yourdomain.com`, or `onboarding@resend.dev` for testing) |
| `EMAIL_TO` | Recipient(s), comma-separated |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_SECURITY` | SMTP fallback instead of Resend |

**Alerts are email-only and fire only when a programme transitions into `OPEN`.** Telegram support
still exists in `notifier.py`, but the workflow sets `NOTIFY_CHANNELS: email`, so Telegram is never
contacted. To bring it back later, drop that line and add `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` — and message the bot once first, because a bot cannot start a chat with you.

### Email via Resend

1. [resend.com](https://resend.com) → sign up → **API Keys → Create API Key** → copy `re_…` into
   `EMAIL_API_KEY`.
2. `EMAIL_FROM` must be a sender Resend has verified: your own domain
   (`alerts@yourdomain.com`), or `onboarding@resend.dev` for testing — the latter can only send to
   the address you signed up with.
3. `EMAIL_TO` = your address.

### Email via SMTP instead

Set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=you@gmail.com`,
`SMTP_SECURITY=starttls`, and `SMTP_PASS=<App Password>`. For Gmail you must enable 2FA and create
an **App Password** — your normal password will be rejected.

---

## 8. Run it once

1. **Actions** tab → left sidebar **Daily pilot cadet check** → **Run workflow**.
2. Leave the branch as `main` and **tick `dry_run`** for the first attempt: alerts are rendered
   into the log instead of sent, and nothing is committed.
3. Open the finished run → the **job summary** shows a Markdown table of all seven programmes with
   their status, evidence and passport tag. The alert step logs the exact email
   payloads, so you can confirm the wording before anything reaches your phone.
4. Run it again with `dry_run` **unchecked** to do it for real.
5. **Prove the email channel works:** run it once more with `self_test` **ticked**. That sends a
   single test alert (subject `🟠 Update — Self test`) through the enabled channels. Alerts
   otherwise only fire on a real transition into `OPEN`, which could be weeks away — so this is
   the only way to confirm delivery before it matters.

Expect the first real run to alert for whatever is currently `OPEN` (Wizz Air and Cathay Pacific as
of the last sweep). That is deliberate: a first-run `OPEN` is treated as a transition, so setup is
never silent.

---

## 9. Verify

```bash
curl -sI https://<USERNAME>.github.io/pilot-tracker/status.json | head -1     # HTTP/2 200
curl -s  https://<USERNAME>.github.io/pilot-tracker/status.json | head -20
```

Also worth opening in a browser: `https://<USERNAME>.github.io/pilot-tracker/` renders a small
status page from the same JSON. The first deploy takes a minute after the run.

---

## 10. Point the widget at it

Send me the URL (or just your username) and I will set `WidgetConfig.defaultStatusURL`, rebuild,
reinstall to `/Applications` and re-register the widget. Until then the widget shows the snapshot
bundled at build time, labelled as offline data with the 404 underneath.

---

## 11. Living with it

- **Timing.** The cron is `0 8 * * *` UTC. GitHub can delay scheduled runs by up to ~15 minutes at
  busy times; it is a daily sweep, not an alarm clock.
- **Keep the schedule alive.** GitHub disables scheduled workflows after **60 days of repository
  inactivity**. The monitor's daily `status.json` commit counts as activity, which is a second
  reason that commit exists.
- **Your clone will diverge.** The bot commits `status.json` daily, so before pushing local work:

  ```bash
  git pull --rebase origin main && git push
  ```

- **Alerts only fire on transitions into `OPEN`** (plus a first-run `OPEN`). A programme that stays
  open does not re-alert. To also hear about `INTEREST`/closures, add `--alert-on-interest` or
  `--alert-on-closed` to the monitor invocation in `daily_check.yml`.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Commit step fails with `403` | Step 5: Workflow permissions are still read-only. |
| Pages URL returns `404` | Pages source is not "GitHub Actions" (step 6), or the `publish` job has not succeeded yet. |
| Alerts say `skipped` | The relevant secrets are unset or misnamed (check exact names, step 7). |
| No email arrives but the run is green | The alert step reported `skipped` — `EMAIL_TO` or the transport secret is missing or misnamed. |
| The run fails at *Flag an undeliverable alert* | Email delivery genuinely failed. The status commit and Pages publish already happened; check the Resend/SMTP credentials. |
| `email skipped (no transport configured)` | Neither `EMAIL_API_KEY` nor `SMTP_HOST` is set. |
| A programme shows `UNKNOWN` | The page was reachable but said nothing decisive — usually a bot wall or a redesign. Aer Lingus does this behind its Imperva WAF. The monitor reports it rather than guessing. |
| Workflow never runs on schedule | Scheduled workflows are disabled on inactive repositories; open the Actions tab and re-enable, and check that Actions are allowed for the repo. |
| `git push` rejected (`fetch first`) | The daily bot commit moved the remote. `git pull --rebase origin main`, then push. |
| Everything errored in one run | The `Fail if every programme errored` step fails the job on purpose: that means the network, the runner or `targets.json` broke, not one portal. |
