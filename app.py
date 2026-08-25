"""
Rwanda Diaspora Resource Database — Click Tracker
---------------------------------------------------
A tiny web service with one job: when someone clicks a resource link,
it logs the click in Airtable, then instantly redirects them to the
real resource URL.

Tracks TWO numbers per resource:
  - Click Count   — every click, same visitor or not (raw engagement)
  - Unique Clicks — each visitor's browser only counted once, using
                    an anonymous cookie (no login, no personal info)

This runs as a Render "Web Service" (always-listening), NOT a cron
job like the weekly pipeline — different Render setup, see notes
at the bottom of this file.
"""

import os
import uuid
import logging
from datetime import date
from flask import Flask, redirect, request, make_response
from pyairtable import Api

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("click_tracker")

app = Flask(__name__)

AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE   = os.environ["AIRTABLE_TABLE"]  # e.g. "RESOURCES"
CLICK_LOG_TABLE  = os.environ.get("CLICK_LOG_TABLE", "Click Log")
URL_FIELD        = os.environ.get("URL_FIELD", "Resource URL")
FALLBACK_URL     = os.environ.get("FALLBACK_URL", "https://airtable.com")
COOKIE_NAME      = "rwanda_visitor_id"
COOKIE_MAX_AGE   = 60 * 60 * 24 * 365  # 1 year

resources_table = Api(AIRTABLE_API_KEY).table(AIRTABLE_BASE_ID, AIRTABLE_TABLE)
click_log_table = Api(AIRTABLE_API_KEY).table(AIRTABLE_BASE_ID, CLICK_LOG_TABLE)


def is_first_click_from_this_visitor(visitor_id: str, record_id: str) -> bool:
    """Checks the Click Log table for this visitor+resource pair.
    Returns True (and logs it) only if this is genuinely new."""
    key = f"{visitor_id}:{record_id}"
    try:
        formula = f"{{Key}}='{key}'"
        existing = click_log_table.all(formula=formula, max_records=1)
        if existing:
            return False
        click_log_table.create({
            "Key": key,
            "Visitor ID": visitor_id,
            "Resource ID": record_id,
            "First Clicked": date.today().isoformat()
        })
        return True
    except Exception as e:
        # If the dedup check itself fails, don't block the redirect —
        # just skip the unique-count increment for this click.
        log.error(f"Click Log lookup/write failed: {e}")
        return False


@app.route("/go/<record_id>")
def go(record_id):
    try:
        record = resources_table.get(record_id)
    except Exception as e:
        log.error(f"Could not find record {record_id}: {e}")
        return redirect(FALLBACK_URL, code=302)

    dest_url = record["fields"].get(URL_FIELD)
    if not dest_url:
        log.error(f"Record {record_id} has no {URL_FIELD} set")
        return redirect(FALLBACK_URL, code=302)

    # Get or create this visitor's anonymous cookie ID
    visitor_id = request.cookies.get(COOKIE_NAME)
    is_new_visitor_cookie = visitor_id is None
    if is_new_visitor_cookie:
        visitor_id = str(uuid.uuid4())

    current_clicks = record["fields"].get("Click Count", 0) or 0
    current_unique = record["fields"].get("Unique Clicks", 0) or 0

    update_fields = {
        "Click Count": current_clicks + 1,
        "Last Clicked": date.today().isoformat()
    }

    if is_first_click_from_this_visitor(visitor_id, record_id):
        update_fields["Unique Clicks"] = current_unique + 1
        log.info(f"New unique visitor for {record_id} (total unique: {current_unique + 1})")

    try:
        resources_table.update(record_id, update_fields)
        log.info(f"Logged click #{current_clicks + 1} for record {record_id}")
    except Exception as e:
        # Never let a logging failure block the redirect — the visitor
        # experience matters more than the analytics.
        log.error(f"Failed to log click for {record_id}: {e}")

    response = make_response(redirect(dest_url, code=302))
    if is_new_visitor_cookie:
        response.set_cookie(COOKIE_NAME, visitor_id, max_age=COOKIE_MAX_AGE,
                             httponly=True, samesite="Lax")
    return response


@app.route("/")
def health():
    return "Click tracker is running.", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


"""
================== SETUP CHECKLIST ==================

1. AIRTABLE FIELDS — add to your Resources table:
   - "Click Count"   (Number field, default 0)   [already exists]
   - "Last Clicked"  (Date field)                [already exists]
   - "Tracked Link"  (Formula field)              [already exists]
   - "Unique Clicks" (Number field, default 0)   *** NEW ***

2. NEW AIRTABLE TABLE — "Click Log" (create this whole table fresh):
   - "Key"            (Single line text) — used to detect repeat visits
   - "Visitor ID"      (Single line text)
   - "Resource ID"     (Single line text)
   - "First Clicked"   (Date)
   This table is just a dedup ledger — no one needs to look at it day
   to day, but don't delete it, since that would reset uniqueness
   tracking for every resource.

3. NEW ENVIRONMENT VARIABLE on Render:
   - CLICK_LOG_TABLE = Click Log   (only needed if you name the table
     something other than "Click Log" — otherwise this has a working
     default and can be skipped)

4. EVERYTHING ELSE — unchanged from before. Same deployment steps,
   same other environment variables, same Tracked Link formula.

NOTE ON WHAT "UNIQUE" ACTUALLY MEANS: this tracks browsers, not
people, using an anonymous cookie — no login, no personal data
collected. The same person clicking from their phone and later
their laptop will count as 2 unique visitors, not 1. There's no
way to fully solve that without requiring visitors to log in,
which isn't realistic for a public resource link. This is the
standard, honest tradeoff for anonymous web analytics.

NOTE ON RENDER'S FREE TIER: free Web Services "spin down" after
15 minutes of no traffic, and the next click wakes it back up with
a ~20-30 second delay before redirecting. Not a big deal for this
use case, but worth knowing so a slow first click doesn't look broken.
"""
