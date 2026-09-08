# Setup — no installing anything

Every step below happens in a web browser. Budget about 20 minutes.

When you're done, GitHub runs the scan automatically each weekday after the
close and emails you the ranked list. Cost: $0.

---

## 1. Make a GitHub account

Go to github.com and sign up. The free plan is all you need.

## 2. Create the repository

Click the **+** in the top right → **New repository**.

- Name it whatever you like, e.g. `swing-scanner`
- Choose **Public**

> **Why public?** Public repos get unlimited Actions minutes and more reliable
> scheduling. Private repos on the free plan have a monthly minute budget and
> there are recurring reports of scheduled jobs not firing reliably on free
> private repos. The only thing in this repo is a list of ticker symbols and
> some code — nothing sensitive. Your email password lives in Secrets, which
> stay private even in a public repo, and your trade log never goes here at all.

- Tick **Add a README file**
- Click **Create repository**

## 3. Upload the files

On the repo page: **Add file** → **Upload files**. Drag in everything from the
zip:

```
swing_scanner.py
report.py
universe.py
universe.txt
requirements.txt
.github/workflows/scan.yml
.github/workflows/universe.yml
results/.gitkeep
```

If dragging the `.github` folder doesn't work in your browser, upload the loose
files first, then use **Add file → Create new file** and type the filename as
`.github/workflows/scan.yml` — GitHub creates the folders for you when you type
slashes. Paste the file contents in, then **Commit changes**.

## 4. Make a Gmail app password

This is a throwaway password that only this script can use. It is not your real
Gmail password, and you can revoke it any time without changing anything else.

1. Your Google Account → **Security**
2. Turn on **2-Step Verification** if it isn't already (required for the next step)
3. Search your Google Account settings for **App passwords**
4. Create one, name it `swing scanner`
5. Copy the 16-character code it shows you — you can't see it again

I'd suggest making a separate Gmail account for this rather than using your main
one. Takes two minutes and keeps the blast radius small.

## 5. Add the secrets

In your repo: **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**. Add these four, one at a time:

| Name | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | the sending Gmail address |
| `SMTP_PASS` | the 16-character app password from step 4 |

Optionally add `MAIL_TO` if you want the report sent somewhere other than the
sending address.

**If you have Finviz Elite**, also add `FINVIZ_AUTH` with the token from
<https://elite.finviz.com/api_explanation.ashx>. That switches fundamentals
from Yahoo to Finviz's official export API — better data, one call instead of
one per ticker, and it adds short interest, float, ownership and analyst
consensus. Leave it out and everything still works on free Yahoo data.

Do not scrape the free Finviz site. It's against their terms of service, and
GitHub Actions runners share IP addresses that get blocked fast.

Secrets are write-only. Nobody can read them back out, including you.

## 6. Build the universe

There's no watchlist to fill in. The scanner picks its own tickers.

Go to **Actions** → **Weekly universe refresh** → **Run workflow**. It pulls
every US listed common stock, screens out ETFs, warrants, units, preferreds
and test issues, then keeps the 1,200 most liquid names and commits the result
as `universe.txt`.

This takes 10-20 minutes the first time. After that it re-runs itself every
Sunday, so delistings drop out and new listings come in without you touching
anything.

You can run the daily scan before this finishes — it ships with a small seed
list so it won't fall over.

## 7. Turn on the web app

In your repo: **Settings** → **Pages**. Under "Build and deployment", set
Source to **Deploy from a branch**, branch **main**, folder **/docs**, then
**Save**.

Give it a minute, then visit:

```
https://YOUR-USERNAME.github.io/swing-scanner/
```

That's your dashboard. It updates itself every time the scanner runs.

**To install it as an app:**

- *iPhone:* open the page in Safari, tap Share, then "Add to Home Screen"
- *Android:* open in Chrome, tap the menu, then "Install app"
- *Desktop:* Chrome or Edge show an install icon in the address bar

It gets its own icon and opens without browser chrome, like any other app.
There is nothing to download from an app store and nothing to package.

## 8. Test it

**Actions** tab → **Daily swing scan** → **Run workflow** → **Run workflow**.

Wait a minute, then refresh. A green tick means it worked — check your inbox,
and reload the dashboard.
A red X means something failed; click into the run and read the red step. It's
almost always a typo in a secret name or a bad ticker symbol.

Run it manually a few times before trusting the schedule.

---

## Things that will confuse you later

**The schedule is approximate.** GitHub's cron runs on shared infrastructure
and does not guarantee exact times. Delays of 10–30 minutes are normal, and
occasionally a run is skipped entirely during peak load. This is fine for an
end-of-day screen. It would not be fine for anything intraday.

**Scheduled workflows get switched off after 60 days of repository inactivity.**
GitHub emails you a warning first. This setup commits its results each run,
which counts as activity, so it should keep itself alive — but if you ever see
the "disabled due to inactivity" banner in the Actions tab, just click **Enable
workflow**.

**Brand-new repos sometimes don't register the cron immediately.** If the
schedule hasn't fired after 24 hours, push any small change to the repo (edit
the README and commit) to nudge the scheduler.

**Daylight saving shifts your run time by an hour.** Cron is UTC and doesn't
observe DST, so the 22:15 UTC run lands at 6:15pm ET in summer and 5:15pm in
winter. Both are after the close, so it doesn't matter. Edit the cron line in
`scan.yml` if you want to change it.

**Yahoo data is free, and priced accordingly.** Occasional bad ticks, missing
days, and unannounced rate limiting. It's fine for end-of-day screening and
learning what criteria work. It is not fine for anything you'd trade
automatically. If the screen becomes something you rely on, that's the point to
pay for a real feed.

---

## What this does not do

It doesn't place trades, and it shouldn't. It produces a ranked list of names
that passed a filter — a starting point for you to look at, nothing more.

The scoring weights (40/30/30) and the stop/target multiples (1.5x and 3x ATR)
are starting assumptions, not tested findings. They exist so you have something
concrete to measure against. Log every candidate in the trade log, including
the ones you skip, and revisit the weights once you have 30+ closed trades and
the Summary tab has something real to say.

Not investment advice.
