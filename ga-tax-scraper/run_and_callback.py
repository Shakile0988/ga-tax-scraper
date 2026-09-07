"""
CLI entrypoint used by the GitHub Actions workflow.

Reads parcel_id / tax_year / callback_url from command-line args (passed in
via workflow_dispatch inputs), runs the scraper, and POSTs the JSON result
back to the n8n webhook URL (callback_url). This lets n8n trigger a GitHub
Actions run and receive the result asynchronously, without any server/VPS.
"""

import sys
import json
import argparse
import urllib.request

from src.scraper import scrape


def post_result(callback_url: str, data: dict):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        callback_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"Posted result to n8n webhook, status={resp.status}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parcel-id", required=True)
    parser.add_argument("--tax-year", required=True)
    parser.add_argument("--callback-url", required=False, default=None,
                         help="n8n webhook URL to POST the JSON result to")
    args = parser.parse_args()

    result = scrape(args.parcel_id, args.tax_year, headless=True)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Always write a local result.json so it can be picked up as a GitHub
    # Actions artifact even if the n8n callback fails for some reason.
    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if args.callback_url:
        try:
            post_result(args.callback_url, result)
        except Exception as e:  # noqa: BLE001
            print(f"Failed to POST result to callback_url: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
