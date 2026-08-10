"""
Rwanda Diaspora Resource Database — Click Tracker
---------------------------------------------------
A tiny web service with one job: when someone clicks a resource link,
it logs the click in Airtable (Click Count +1, Last Clicked = today),
then instantly redirects them to the real resource URL.

This runs as a Render "Web Service" (always-listening), NOT a cron
job like the weekly pipeline — different Render setup, see notes
at the bottom of this file.
"""

import os
import logging
from datetime import date
from flask import Flask, redirect, abort
from pyairtable import Api

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("click_tracker")

app = Flask(__name__)

AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE   = os.environ["AIRTABLE_TABLE"]  # e.g. "Resources"
URL_FIELD        = os.environ.get("URL_FIELD", "Resource URL")
FALLBACK_URL     = os.environ.get("FALLBACK_URL", "https://airtable.com")

table = Api(AIRTABLE_API_KEY).table(AIRTABLE_BASE_ID, AIRTABLE_TABLE)


@app.route("/go/<record_id>")
def go(record_id):
    try:
        record = table.get(record_id)
    except Exception as e:
        log.error(f"Could not find record {record_id}: {e}")
        return redirect(FALLBACK_URL, code=302)

    dest_url = record["fields"].get(URL_FIELD)
    if not dest_url:
        log.error(f"Record {record_id} has no {URL_FIELD} set")
        return redirect(FALLBACK_URL, code=302)

    current_clicks = record["fields"].get("Click Count", 0) or 0
    try:
        table.update(record_id, {
            "Click Count": current_clicks + 1,
            "Last Clicked": date.today().isoformat()
        })
        log.info(f"Logged click #{current_clicks + 1} for record {record_id}")
    except Exception as e:
        # Never let a logging failure block the redirect — the visitor
        # experience matters more than the analytics.
        log.error(f"Failed to log click for {record_id}: {e}")

    return redirect(dest_url, code=302)


@app.route("/")
def health():
    return "Click tracker is running.", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


"""
================== SETUP CHECKLIST ==================

1. AIRTABLE FIELDS — add to your Resources table:
   - "Click Count"   (Number field, default 0)
   - "Last Clicked"  (Date field)
   - "Tracked Link"  (Formula field — see step 4 below)

2. FILES FOR DEPLOYMENT
   Alongside this app.py, create:
     requirements.txt:
         flask
         pyairtable
         gunicorn

3. DEPLOY TO RENDER (as a WEB SERVICE, not a cron job)
   - render.com → New → Web Service → connect the GitHub repo
     with these files.
   - Build command:   pip install -r requirements.txt
   - Start command:   gunicorn app:app
   - Environment variables to add:
       AIRTABLE_API_KEY = your token
       AIRTABLE_BASE_ID = appYtbsPDecTDYwnH  (or your Resources base)
       AIRTABLE_TABLE   = Resources   (exact table name)
       URL_FIELD        = Resource URL  (exact field name holding the real link)
   - Deploy. Render will give you a live URL like:
       https://rwanda-click-tracker.onrender.com

4. ADD THE "TRACKED LINK" FORMULA FIELD IN AIRTABLE
   Field type: Formula. Formula:
       "https://rwanda-click-tracker.onrender.com/go/" & RECORD_ID()
   (replace with YOUR actual Render URL from step 3)

5. POINT THE INTERFACE AT THE TRACKED LINK
   In your published Interface, edit the List/Gallery element's
   link/button so it opens "Tracked Link" instead of the raw
   "Resource URL" field. Visitors won't notice any difference —
   they still land on the real page, just via one quick hop.

6. VERIFY IT WORKS
   Click a resource from the live Interface. Then check Airtable:
   "Click Count" on that record should be 1, "Last Clicked" should
   be today. If it doesn't update, check Render's logs (render.com
   → your service → Logs) for the actual error.

NOTE ON RENDER'S FREE TIER: free Web Services "spin down" after
15 minutes of no traffic, and the next click wakes it back up with
a ~20-30 second delay before redirecting. Not a big deal for this
use case, but worth knowing so a slow first click doesn't look broken.
"""
