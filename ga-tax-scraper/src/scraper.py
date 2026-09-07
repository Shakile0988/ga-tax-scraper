"""
Athens-Clarke County, GA Property Tax Scraper
================================================
Scrapes property tax bill details from:
    https://athensclarkecounty.governmentwindow.com/tax.html

Why Playwright (real browser) instead of plain requests/curl?
- The site sits behind Cloudflare, which requires a JS challenge to be solved
  (cf_clearance cookie). Plain HTTP libraries cannot pass this reliably.
- The final bill detail page uses a dynamic `bill_id` token
  (e.g. bill_id=3D521214G98526L3712) that is generated server-side per
  session/search and is NOT the same as the visible `bill_no`. It can only
  be obtained by actually clicking through the search flow.

Flow automated here:
  1. Open tax.html?tax_year=<YEAR>
  2. Enter Map/Parcel ID, click "Search by Map/Parcel"
  3. On the results page, filter by Year (if more than one year is present)
  4. Click the Bill # link matching the requested year
  5. Scrape the resulting bill detail page (pay_bill.html)
"""

from __future__ import annotations

import re
import sys
import json
import time
import logging
from dataclasses import dataclass, asdict
from typing import Optional

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ga_tax_scraper")

BASE_URL = "https://athensclarkecounty.governmentwindow.com"


@dataclass
class BillResult:
    parcel_id: str
    tax_year: str
    bill_no: Optional[str] = None
    owner_name: Optional[str] = None
    property_address: Optional[str] = None
    map_code: Optional[str] = None
    due_date: Optional[str] = None
    current_due: Optional[str] = None
    prior_payment: Optional[str] = None
    back_taxes: Optional[str] = None
    total_due: Optional[str] = None
    status: Optional[str] = None
    raw_page_url: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class GATaxScraper:
    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        self._context.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def scrape_parcel(self, parcel_id: str, tax_year: str) -> BillResult:
        result = BillResult(parcel_id=parcel_id, tax_year=str(tax_year))
        page = self._context.new_page()
        try:
            self._wait_for_cloudflare(page, f"{BASE_URL}/tax.html?tax_year={tax_year}&")
            self._search_by_parcel(page, parcel_id)
            self._filter_by_year(page, tax_year)
            bill_page = self._open_bill(page, tax_year)
            self._extract_bill_details(bill_page, result)
            result.raw_page_url = bill_page.url
        except PWTimeout as e:
            result.error = f"Timeout: {e}"
            log.error("Timeout while scraping parcel %s: %s", parcel_id, e)
        except Exception as e:  # noqa: BLE001
            result.error = str(e)
            log.exception("Error scraping parcel %s", parcel_id)
        finally:
            page.close()
        return result

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------
    def _wait_for_cloudflare(self, page: Page, url: str):
        log.info("Opening %s", url)
        page.goto(url, wait_until="domcontentloaded")
        # Give Cloudflare's JS challenge time to resolve if present.
        for _ in range(15):
            if "Just a moment" in page.title() or "challenge" in page.url:
                time.sleep(1)
                continue
            break
        page.wait_for_selector("input#map_code, input[name='map_code']", timeout=self.timeout_ms)

    def _search_by_parcel(self, page: Page, parcel_id: str):
        log.info("Searching by Map/Parcel ID: %s", parcel_id)
        selector = "input#map_code, input[name='map_code']"
        page.fill(selector, parcel_id)
        # Button text observed: "Search by Map/Parcel"
        page.click("text=Search by Map/Parcel")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_selector("table, .no-results, text=Property Tax Search Results", timeout=self.timeout_ms)

    def _filter_by_year(self, page: Page, tax_year: str):
        """If a Year filter dropdown exists and more than one year is shown,
        select the requested year to narrow the results table."""
        year_dropdown = page.locator("select[name*='year' i], .year-filter select")
        if year_dropdown.count() > 0:
            try:
                log.info("Filtering results by year %s", tax_year)
                year_dropdown.first.select_option(label=str(tax_year))
                page.wait_for_load_state("domcontentloaded")
                time.sleep(1)
            except Exception:
                log.warning("Could not select year %s from dropdown, continuing", tax_year)

    def _open_bill(self, page: Page, tax_year: str) -> Page:
        """Find the row matching tax_year and click its Bill # link."""
        log.info("Locating Bill # link for year %s", tax_year)
        # Try to find a table row containing the year, then the bill link in that row.
        row = page.locator(f"tr:has-text('{tax_year}')").first
        bill_link = row.locator("a").first
        if bill_link.count() == 0:
            # Fallback: just grab the first bill-looking link on the page.
            bill_link = page.locator("a[href*='pay_bill.html']").first

        with page.expect_navigation(wait_until="domcontentloaded"):
            bill_link.click()
        return page

    def _extract_bill_details(self, page: Page, result: BillResult):
        log.info("Extracting bill details from %s", page.url)
        content = page.content()

        def grab(label: str) -> Optional[str]:
            m = re.search(rf"{re.escape(label)}\s*[:\-]?\s*</?\w*>?\s*([^<\n]+)", content, re.IGNORECASE)
            return m.group(1).strip() if m else None

        # Prefer structured table cell extraction where possible.
        result.bill_no = self._text_after_label(page, "Bill No")
        result.owner_name = self._text_after_label(page, "Name") or self._text_after_label(page, "Owner")
        result.property_address = self._text_after_label(page, "Location") or self._text_after_label(page, "Property Address")
        result.map_code = self._text_after_label(page, "Map")
        result.due_date = self._text_after_label(page, "Due Date")
        result.current_due = self._text_after_label(page, "Current Due")
        result.prior_payment = self._text_after_label(page, "Prior Payment")
        result.back_taxes = self._text_after_label(page, "Back Taxes")
        result.total_due = self._text_after_label(page, "Total Due")
        result.status = "Paid" if "Paid" in content else ("Due" if result.total_due else None)

    @staticmethod
    def _text_after_label(page: Page, label: str) -> Optional[str]:
        try:
            locator = page.locator(f"text={label}").first
            if locator.count() == 0:
                return None
            # Try sibling cell (table layout) first.
            sibling = locator.locator("xpath=following-sibling::*[1]")
            if sibling.count() > 0:
                txt = sibling.inner_text().strip()
                if txt:
                    return txt
            # Fallback: parent's full text minus the label.
            parent_text = locator.locator("xpath=..").inner_text()
            cleaned = parent_text.replace(label, "").strip(" :\n\t")
            return cleaned or None
        except Exception:
            return None


def scrape(parcel_id: str, tax_year: str, headless: bool = True) -> dict:
    with GATaxScraper(headless=headless) as scraper:
        result = scraper.scrape_parcel(parcel_id, tax_year)
    return result.to_dict()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scraper.py <parcel_id> <tax_year> [--visible]")
        sys.exit(1)
    parcel = sys.argv[1]
    year = sys.argv[2]
    headless = "--visible" not in sys.argv
    data = scrape(parcel, year, headless=headless)
    print(json.dumps(data, indent=2, ensure_ascii=False))
