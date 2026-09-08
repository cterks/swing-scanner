"""
Builds the HTML email: one card per candidate showing the setup name, why it
matched, the trade levels, and a link straight to its TradingView chart.

Credentials come from environment variables (GitHub Secrets):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO

If SMTP_USER or SMTP_PASS is missing, sending is skipped and the HTML is just
written to disk, which makes local and notebook testing safe.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

CSS = """
body{font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#1a1a1a;
     line-height:1.55;max-width:720px;margin:0 auto;padding:8px}
h2{font-size:19px;margin:0 0 2px}
.sub{font-size:13px;color:#666;margin:0 0 20px}
.card{border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin:0 0 14px}
.hdr{border-bottom:1px solid #eee;padding-bottom:8px;margin-bottom:10px}
.tk{font-size:18px;font-weight:700}
.setup{display:inline-block;background:#1F3864;color:#fff;font-size:11px;
       font-weight:600;padding:3px 8px;border-radius:10px;margin-left:8px}
.also{font-size:11px;color:#888;margin-left:6px}
.px{float:right;font-size:16px;font-weight:600;color:#333}
.biz{font-size:12px;color:#666;margin:0 0 10px}
.why{margin:0 0 12px;padding-left:18px;font-size:13px}
.why li{margin:3px 0}
.lv{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0}
.lv td{padding:5px 8px;border-bottom:1px solid #f0f0f0}
.lv td:first-child{color:#666;width:38%}
.lv td:last-child{text-align:right;font-variant-numeric:tabular-nums;
                  font-weight:600}
.fund{font-size:12px;background:#fafafa;border-radius:6px;padding:9px 12px;
      margin:10px 0}
.fund b{font-size:11px;text-transform:uppercase;letter-spacing:.4px}
.g-Strong,.g-Sound{color:#1a7f37}
.g-Mixed{color:#9a6700}
.g-Weak{color:#b42318}
.g-Nodata{color:#888}
.fund ul{margin:5px 0 0;padding-left:16px}
.tv{display:inline-block;margin-top:6px;font-size:13px;color:#1F3864;
    text-decoration:none;font-weight:600}
.note{font-size:12px;color:#666;margin-top:24px;border-top:1px solid #e5e5e5;
      padding-top:14px}
.none{background:#f5f5f5;padding:18px;border-radius:8px;color:#555}
"""


def _card(r):
    setup = r.get("setup", "-")
    also = [s for s in r.get("all_setups", []) if s != setup]
    also_html = (f'<span class="also">also: {", ".join(also)}</span>'
                 if also else "")

    why = "".join(f"<li>{w}</li>" for w in r.get("reasons", []))

    grade = r.get("fund_grade", "No data")
    gcls = "g-" + grade.replace(" ", "").capitalize()
    fnotes = "".join(f"<li>{n}</li>" for n in r.get("fund_notes", []))

    tv = r.get("tv_url")
    tv_html = (f'<a class="tv" href="{tv}">Open {r["ticker"]} on TradingView &rarr;</a>'
               if tv else "")

    return f"""<div class="card">
<div class="hdr">
  <span class="px">${r['price']:,.2f}</span>
  <span class="tk">{r['ticker']}</span>
  <span class="setup">{setup}</span>{also_html}
</div>
<p class="biz">{r.get('business', '-')}</p>

<b style="font-size:12px">Why it showed up</b>
<ul class="why">{why}</ul>

<table class="lv">
<tr><td>Entry trigger (buy stop)</td><td>${r['entry']:,.2f}</td></tr>
<tr><td>Stop ({r.get('stop_basis', '')})</td><td>${r['stop']:,.2f}</td></tr>
<tr><td>Risk per share</td>
    <td>${r['risk_per_share']:,.2f} ({r['risk_pct']:.1f}%)</td></tr>
<tr><td>First target (2R)</td><td>${r['target_2r']:,.2f}</td></tr>
<tr><td>Second target (3R)</td><td>${r['target_3r']:,.2f}</td></tr>
</table>

<div class="fund"><b class="{gcls}">Fundamentals: {grade}</b>
<ul>{fnotes}</ul></div>

{tv_html}
</div>"""


def build_html(rows, run_date, scanned, bench_return):
    if not rows:
        body = ('<div class="none">No setups matched today. That is a normal '
                'result, not a failure - every setup requires an intact '
                'uptrend, so a weak market should return nothing.</div>')
        n = 0
    else:
        body = "".join(_card(r) for r in rows)
        n = len(rows)

    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h2>Swing scan &mdash; {run_date}</h2>
<p class="sub">{n} setup{'' if n == 1 else 's'} found across {scanned}
tickers. SPY 60-day return: {bench_return:+.1%}</p>
{body}
<div class="note">
<b>What these numbers are and are not.</b>
The entry is a <i>buy stop</i> above the prior day's high, so it only fills if
the stock actually turns up &mdash; it is not an instruction to buy at the open.
Stops sit below the 10-day swing low, capped at 2x ATR. Targets are 2x and 3x
the entry-to-stop distance.<br><br>
These levels are a consistent framework for measuring the screen, not tested
parameters. The fundamental grade is four crude checks on margins, growth,
returns and leverage &mdash; a sanity check on the business, not a valuation.<br><br>
Log every name here in your trade log, including the ones you skip, and record
where the price landed at +5 and +20 days. Judge the screen on 30+ closed
trades, never on one day. Not investment advice.
</div>
</body></html>"""


def _env(name, default=None):
    """
    Read an environment variable, treating empty as unset.

    GitHub Actions sets env vars for secrets that don't exist to an EMPTY
    STRING rather than leaving them undefined, so os.environ.get(name,
    default) returns "" instead of the default. That turned an optional
    feature into a crash.
    """
    v = os.environ.get(name)
    return default if v is None or not v.strip() else v.strip()


def send(html, subject, out_path="report.html", attach=None):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")

    # Check credentials BEFORE parsing anything else. Email is optional and
    # must never be able to fail a run whose real work already succeeded.
    if not user or not password:
        print(f"No email credentials set - skipped sending. Wrote {out_path}")
        return False

    host = _env("SMTP_HOST", "smtp.gmail.com")
    try:
        port = int(_env("SMTP_PORT", "587"))
    except ValueError:
        print("SMTP_PORT is not a number - falling back to 587.")
        port = 587
    to = _env("MAIL_TO") or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content("This report is HTML. Open it in a client that renders HTML.")
    msg.add_alternative(html, subtype="html")

    # Attach the TradingView watchlist so it imports straight from the email.
    if attach and os.path.exists(attach):
        with open(attach, "rb") as f:
            msg.add_attachment(f.read(), maintype="text", subtype="plain",
                               filename=os.path.basename(attach))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(user, password)
            server.send_message(msg)
    except Exception as e:
        # The scan already succeeded and the data is on disk. Losing the day's
        # results because a mail server refused a connection would be absurd.
        print(f"\nCould not send email ({type(e).__name__}: {e}).")
        print("The scan itself succeeded - results and dashboard are written.")
        if "auth" in str(e).lower() or "password" in str(e).lower():
            print("That looks like a credentials problem. Check SMTP_USER is "
                  "the full address and SMTP_PASS is a 16-character Gmail app "
                  "password with no spaces.")
        return False

    print(f"Emailed report to {to}")
    return True
