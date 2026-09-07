"""
Basic smoke test. Run manually with:
    python -m tests.test_scraper

Note: this hits the live website, so it is not run automatically in CI
(no network access / could break if the site changes). Use it locally to
verify the scraper still works after any site changes.
"""

from src.scraper import scrape


def test_scrape_known_parcel():
    result = scrape(parcel_id="152 0114", tax_year="2021", headless=True)
    print(result)
    assert result.get("error") is None, f"Scrape failed: {result.get('error')}"
    assert result.get("bill_no") is not None


if __name__ == "__main__":
    test_scrape_known_parcel()
    print("OK")
