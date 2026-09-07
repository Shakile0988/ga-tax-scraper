# Athens-Clarke County GA Property Tax Scraper

Scrapes property tax bill details from
`https://athensclarkecounty.governmentwindow.com/tax.html` given a
**Parcel/Map ID** and a **Tax Year**.

## Why a real browser (Playwright)?

Two things make plain `requests`/`curl` scraping impossible here:

1. **Cloudflare** protects the site with a JS challenge (`cf_clearance`
   cookie). Only a real (or real-looking) browser can solve it.
2. The final bill detail page (`pay_bill.html`) is addressed by a
   **dynamic `bill_id` token** (e.g. `bill_id=3D521214G98526L3712`) that is
   generated per-search/session — it is *not* the same as the visible
   `bill_no`, and can only be obtained by actually clicking through the
   site's search flow (parcel search → results → year filter → bill link).

So this project drives a headless Chromium browser through the exact same
click path a human would use.

## Setup

```bash
git clone <this-repo>
cd ga-tax-scraper
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium     # downloads the browser binary
```

## Usage — command line

```bash
python -m src.scraper "152 0114" 2021
```

Add `--visible` to watch the browser while it works (useful for debugging):

```bash
python -m src.scraper "152 0114" 2021 --visible
```

Output is JSON, e.g.:

```json
{
  "parcel_id": "152 0114",
  "tax_year": "2021",
  "bill_no": "2021-20336",
  "owner_name": "JOHNSON ARTHUR & ARTHUR JOHNSON JR",
  "property_address": "120 BOOKER ST",
  "map_code": "164C4 D026",
  "due_date": "10/20/2021",
  "current_due": "$0.00",
  "prior_payment": "$245.16",
  "back_taxes": "$0.00",
  "total_due": "Paid 12/07/2021",
  "status": "Paid",
  "raw_page_url": "https://athensclarkecounty.governmentwindow.com/pay_bill.html?bill_id=3D521214G98526L3712",
  "error": null
}
```

## Usage — as an HTTP API (for n8n)

Run the API server:

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Call it:

```
GET http://localhost:8000/scrape?parcel_id=152%200114&tax_year=2021
```

### Connecting from n8n

1. Add an **HTTP Request** node.
2. Method: `GET`
3. URL: `http://<your-server>:8000/scrape`
4. Query Parameters: `parcel_id`, `tax_year` (map these from your workflow's
   trigger data — e.g. a spreadsheet row, webhook payload, etc.)
5. The node's output will be the JSON shown above — feed it into whatever
   comes next in your workflow (Google Sheets, database, Slack alert, etc.)

If n8n and this API run on different machines, make sure port 8000 (or
whatever you choose) is reachable from the n8n host, and consider adding
basic auth / an API key in front of it if it's exposed to the internet.

## Running with NO server/VPS — GitHub Actions + n8n webhook

If you don't want to run any server at all, use GitHub Actions as the
"runner" and have it call back to an n8n Webhook node when done.

**1. Push this repo to GitHub** (as-is, `.github/workflows/scrape.yml` is
already included).

**2. Create a Personal Access Token** on GitHub (Settings → Developer
settings → Personal access tokens) with the `repo` and `workflow` scopes.
Store it somewhere n8n can use it (e.g. an n8n credential or environment
variable).

**3. In n8n, add a Webhook node** (this receives the final scrape result).
Copy its **Production URL** — this is your `callback_url`.

**4. In n8n, add an HTTP Request node** that *triggers* the GitHub Action:

- Method: `POST`
- URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/scrape.yml/dispatches`
- Headers:
  - `Authorization: Bearer <your GitHub PAT>`
  - `Accept: application/vnd.github+json`
- Body (JSON):
  ```json
  {
    "ref": "main",
    "inputs": {
      "parcel_id": "152 0114",
      "tax_year": "2021",
      "callback_url": "https://<your-n8n-domain>/webhook/ga-tax-result"
    }
  }
  ```

**5. Wire it up in n8n:**
```
[Trigger node: e.g. Webhook / Schedule / Form]
        ↓
[HTTP Request: dispatch GitHub Action]  (step 4 above)
        ↓
[Webhook node: "ga-tax-result"]  ← GitHub Action calls this back with JSON
        ↓
[...rest of your workflow: Sheets / DB / Slack / etc.]
```

That's the whole loop: **n8n → GitHub Actions (does the actual scraping) →
n8n webhook receives the result.** No VPS, no server, no local machine
needed — everything runs on GitHub's own infrastructure.

> Note: GitHub Actions runs are asynchronous — the dispatch call returns
> immediately (HTTP 204), and the actual result arrives later at your
> Webhook node once the Action finishes (scraping usually takes ~15-30
> seconds). Don't expect the dispatch HTTP Request node to return the data
> directly — the second Webhook node is what actually receives it.

## Project structure

```
ga-tax-scraper/
├── src/
│   ├── scraper.py     # core Playwright scraping logic
│   ├── api.py         # FastAPI wrapper for n8n / HTTP use
│   └── __init__.py
├── tests/
│   └── test_scraper.py
├── requirements.txt
└── README.md
```

## Known limitations / things to watch for

- **Site changes**: if Athens-Clarke County changes their HTML structure,
  the label-based extraction in `_extract_bill_details` may need updating.
- **Cloudflare challenges can escalate**: if scraping is done at high
  volume, Cloudflare may serve a harder challenge (e.g. CAPTCHA) that
  headless Chromium cannot solve automatically. Keep request volume
  reasonable and consider adding delays between parcels.
- **Multiple bills per year**: if a parcel has more than one bill row for
  the same year, the scraper currently takes the first match. Adjust
  `_open_bill` if you need different behavior.
