"""
FastAPI wrapper so n8n (or anything else) can call the scraper over HTTP.

Run locally:
    uvicorn src.api:app --host 0.0.0.0 --port 8000

Then from n8n, use an HTTP Request node:
    GET http://<host>:8000/scrape?parcel_id=152%200114&tax_year=2021
"""

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from .scraper import scrape

app = FastAPI(title="GA Property Tax Scraper", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/scrape")
def scrape_endpoint(
    parcel_id: str = Query(..., description="Map/Parcel/Property ID, e.g. '152 0114'"),
    tax_year: str = Query(..., description="Tax year, e.g. '2021'"),
):
    try:
        data = scrape(parcel_id, tax_year, headless=True)
        return JSONResponse(content=data)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})
