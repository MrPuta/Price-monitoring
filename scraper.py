"""Pobiera ceny kart graficznych i dopisuje je do data/prices.csv."""
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
PRODUCTS_FILE = ROOT / "products.json"
CSV_FILE = ROOT / "data" / "prices.csv"
FIELDS = ["timestamp_utc", "product", "url", "price", "currency", "status"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


def parse_price(text):
    """'2 499,00 zł' / '2,499.00' / '2499' -> 2499.0"""
    text = str(text).replace("\xa0", " ")
    m = re.search(r"\d[\d\s.,]*", text)
    if not m:
        raise ValueError(f"Nie znaleziono ceny w: {text!r}")
    num = re.sub(r"\s", "", m.group(0)).strip(".,")
    if "," in num and "." in num:
        # ostatni separator to separator dziesiętny
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")
    return float(num)


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def from_json_ld(soup):
    """Najpewniejsza metoda: dane schema.org (Offer) w <script type=ld+json>."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk(data):
            if "price" in node and node.get("@type", "") in ("Offer", "AggregateOffer"):
                return parse_price(node["price"]), node.get("priceCurrency", "PLN")
            if "lowPrice" in node:
                return parse_price(node["lowPrice"]), node.get("priceCurrency", "PLN")
    return None


def from_meta(soup):
    tag = soup.find("meta", property="product:price:amount") or soup.find(
        "meta", itemprop="price"
    )
    if tag and tag.get("content"):
        cur = soup.find("meta", property="product:price:currency")
        return parse_price(tag["content"]), (cur["content"] if cur else "PLN")
    return None


def from_selector(soup, selector):
    el = soup.select_one(selector)
    if not el:
        return None
    raw = el.get("content") or el.get_text(" ", strip=True)
    return parse_price(raw), "PLN"


def fetch_price(url, selector=None):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    methods = [lambda: from_selector(soup, selector)] if selector else []
    methods += [lambda: from_json_ld(soup), lambda: from_meta(soup)]
    for method in methods:
        result = method()
        if result:
            return result
    raise ValueError("Nie udało się znaleźć ceny (ustaw 'selector' w products.json)")


def main():
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    CSV_FILE.parent.mkdir(exist_ok=True)
    new_file = not CSV_FILE.exists()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errors = 0

    with CSV_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for p in products:
            row = {"timestamp_utc": now, "product": p["name"], "url": p["url"],
                   "price": "", "currency": "", "status": "ok"}
            try:
                row["price"], row["currency"] = fetch_price(p["url"], p.get("selector"))
                print(f"{p['name']}: {row['price']} {row['currency']}")
            except Exception as e:  # zapisujemy też błędy, żeby widzieć luki w danych
                row["status"] = f"error: {e}"[:200]
                errors += 1
                print(f"{p['name']}: {row['status']}", file=sys.stderr)
            writer.writerow(row)

    sys.exit(1 if errors == len(products) else 0)


if __name__ == "__main__":
    main()
