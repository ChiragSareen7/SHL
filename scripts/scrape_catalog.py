"""
SHL Product Catalog Scraper

Fetches all Individual Test Solutions from https://www.shl.com/solutions/products/productcatalog/
and saves structured data to catalog.json.

Run this script before starting the API server to refresh the catalog:
    python scripts/scrape_catalog.py

The script uses a multi-pass approach:
  1. Fetches paginated catalog listings via the SHL catalog API
  2. Extracts metadata from each product's detail page
  3. Merges with existing catalog.json (seed data) to avoid data loss
"""

import json
import re
import time
import logging
from pathlib import Path
from typing import Optional
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CATALOG_URL = "https://www.shl.com/solutions/products/productcatalog/"
PRODUCT_BASE = "https://www.shl.com"
CATALOG_PATH = Path(__file__).parent.parent / "catalog.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

INDIVIDUAL_TEST_TYPES = {"A", "B", "C", "D", "K", "M", "P", "S"}


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_catalog_page(session: requests.Session, start: int = 0, rows: int = 12) -> Optional[BeautifulSoup]:
    """Fetch a paginated catalog listing page."""
    params = {
        "start": start,
        "type": "A&type=B&type=C&type=D&type=K&type=M&type=P&type=S",
    }
    try:
        r = session.get(CATALOG_URL, params={"start": start}, timeout=20)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        log.warning(f"Failed to fetch catalog page (start={start}): {e}")
        return None


def parse_product_links(soup: BeautifulSoup) -> list[dict]:
    """Extract product name and URL from catalog listing page."""
    products = []

    # Look for product cards / table rows in the catalog
    # SHL catalog uses a table with class "custom-table"
    for row in soup.select("table tbody tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        link_tag = row.find("a", href=True)
        if not link_tag:
            continue
        href = link_tag["href"]
        if "/product-catalog/view/" not in href:
            continue
        name = link_tag.get_text(strip=True)
        url = href if href.startswith("http") else PRODUCT_BASE + href
        # Extract test type codes from cells
        test_type_raw = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        products.append({"name": name, "url": url, "test_type": test_type_raw})

    # Fallback: look for any product links in the page
    if not products:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product-catalog/view/" in href:
                name = a.get_text(strip=True)
                if name:
                    url = href if href.startswith("http") else PRODUCT_BASE + href
                    products.append({"name": name, "url": url, "test_type": ""})

    return products


def fetch_product_detail(session: requests.Session, url: str) -> dict:
    """Fetch and parse a product detail page."""
    result = {}
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Description — try multiple selectors
        for sel in [
            ".product-description",
            ".product-hero__description",
            '[class*="description"]',
            ".content-block p",
            "main p",
        ]:
            desc_tag = soup.select_one(sel)
            if desc_tag and len(desc_tag.get_text(strip=True)) > 30:
                result["description"] = desc_tag.get_text(" ", strip=True)
                break

        # Duration
        for tag in soup.find_all(string=re.compile(r"\d+\s*min", re.I)):
            result["duration"] = tag.strip()
            break

        # Languages — look for language lists
        lang_section = soup.find(string=re.compile(r"language", re.I))
        if lang_section and lang_section.parent:
            sibling = lang_section.parent.find_next_sibling()
            if sibling:
                langs = [li.get_text(strip=True) for li in sibling.find_all("li")]
                if langs:
                    result["languages"] = langs

        # Keys / test categories
        for sel in [".product-tag", ".test-type", '[class*="tag"]']:
            tags = soup.select(sel)
            if tags:
                result["keys"] = [t.get_text(strip=True) for t in tags]
                break

    except Exception as e:
        log.warning(f"Failed to fetch detail for {url}: {e}")

    return result


def determine_test_type_code(keys: list[str]) -> str:
    """Map descriptive keys to single-letter test type codes."""
    mapping = {
        "ability": "A",
        "aptitude": "A",
        "biodata": "B",
        "situational": "B",
        "competenc": "C",
        "development": "D",
        "360": "D",
        "knowledge": "K",
        "skills": "K",
        "motivation": "M",
        "personality": "P",
        "behavior": "P",
        "behaviour": "P",
        "simulation": "S",
    }
    codes = set()
    for key in keys:
        key_l = key.lower()
        for keyword, code in mapping.items():
            if keyword in key_l:
                codes.add(code)
    return ",".join(sorted(codes)) if codes else "K"


def scrape_all_products(session: requests.Session) -> list[dict]:
    """Paginate through the full catalog and collect all products."""
    all_products = []
    seen_urls = set()
    start = 0
    page_size = 12

    log.info("Starting catalog scrape...")
    while True:
        soup = fetch_catalog_page(session, start=start)
        if not soup:
            break

        products = parse_product_links(soup)
        if not products:
            log.info(f"No products found at start={start}, stopping pagination.")
            break

        new_count = 0
        for p in products:
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                all_products.append(p)
                new_count += 1

        log.info(f"Page start={start}: found {len(products)} products ({new_count} new), total={len(all_products)}")

        # Check if there's a next page
        next_btn = soup.find("a", string=re.compile(r"next", re.I)) or soup.find(
            "a", attrs={"aria-label": re.compile(r"next", re.I)}
        )
        if not next_btn:
            break

        start += page_size
        time.sleep(1)  # polite delay

    return all_products


def enrich_products(session: requests.Session, products: list[dict]) -> list[dict]:
    """Fetch detail pages for each product to get descriptions."""
    enriched = []
    for i, p in enumerate(products):
        log.info(f"Enriching {i+1}/{len(products)}: {p['name']}")
        detail = fetch_product_detail(session, p["url"])
        merged = {**p, **detail}

        # Ensure test_type code is set
        if not merged.get("test_type") or merged["test_type"] == "":
            keys = merged.get("keys", [])
            merged["test_type"] = determine_test_type_code(keys)

        enriched.append(merged)
        time.sleep(0.5)

    return enriched


def merge_with_seed(scraped: list[dict], seed_path: Path) -> list[dict]:
    """
    Merge freshly scraped products with existing catalog.json.
    Scraped data takes precedence; seed fills gaps for unknown items.
    """
    if not seed_path.exists():
        return scraped

    with open(seed_path) as f:
        seed = json.load(f)

    seed_by_url = {item["url"]: item for item in seed}
    scraped_by_url = {item["url"]: item for item in scraped}

    # Union: scraped + any seed items not in scraped
    merged = []
    for url, item in scraped_by_url.items():
        seed_item = seed_by_url.get(url, {})
        # Fill missing fields from seed
        for field in ["description", "keys", "duration", "languages"]:
            if not item.get(field) and seed_item.get(field):
                item[field] = seed_item[field]
        merged.append(item)

    for url, item in seed_by_url.items():
        if url not in scraped_by_url:
            merged.append(item)

    return merged


def run():
    session = get_session()

    scraped = scrape_all_products(session)

    if scraped:
        log.info(f"Scraped {len(scraped)} products. Enriching with detail pages...")
        scraped = enrich_products(session, scraped)
        final = merge_with_seed(scraped, CATALOG_PATH)
        log.info(f"Final catalog size: {len(final)} products")
    else:
        log.warning(
            "Scraping returned 0 products (likely JavaScript-rendered page). "
            "Using existing catalog.json seed data."
        )
        if CATALOG_PATH.exists():
            with open(CATALOG_PATH) as f:
                final = json.load(f)
            log.info(f"Loaded {len(final)} products from seed catalog.")
        else:
            log.error("No catalog.json found and scraping failed.")
            return

    with open(CATALOG_PATH, "w") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    log.info(f"Saved catalog to {CATALOG_PATH}")


if __name__ == "__main__":
    run()
