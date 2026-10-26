"""Pobiera ceny kart graficznych i dopisuje je do data/prices.csv."""
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
PRODUCTS_FILE = ROOT / "products.json"
CSV_FILE = ROOT / "data" / "prices.csv"
FIELDS = ["timestamp_utc", "product_id", "model", "vram_gb", "shop",
          "price", "currency", "status", "url"]

TZ = ZoneInfo("Europe/Warsaw")
SLOT_HOURS = (8, 20)             # pomiary ok. 8:00 i 20:00 czasu polskiego
MAX_LATE = timedelta(hours=6)    # po tylu godzinach od pory pomiaru uznajemy okno za stracone

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


def shop_from_url(url):
    """https://www.x-kom.pl/p/123 -> x-kom.pl"""
    return urlparse(url).netloc.removeprefix("www.")


def open_csv():
    """Otwiera CSV do dopisywania. Jeśli nagłówek jest stary, robi kopię zapasową."""
    if CSV_FILE.exists():
        with CSV_FILE.open(encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        if header != FIELDS:
            backup = CSV_FILE.with_name("prices_old_format.csv")
            CSV_FILE.rename(backup)
            print(f"Zmieniony format - stary plik zapisano jako {backup.name}")
    new_file = not CSV_FILE.exists()
    f = CSV_FILE.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    if new_file:
        writer.writeheader()
    return f, writer


def current_slot(now_utc):
    """Ostatnia zaplanowana pora pomiaru (8:00 / 20:00 PL), która już minęła (w UTC)."""
    now = now_utc.astimezone(TZ)
    slots = []
    for delta in (0, -1):
        day = (now + timedelta(days=delta)).date()
        for h in SLOT_HOURS:
            slots.append(datetime(day.year, day.month, day.day, h, tzinfo=TZ))
    return max(t for t in slots if t <= now).astimezone(timezone.utc)


def is_due(now_utc):
    """Czy trzeba teraz zrobić pomiar? Zwraca (bool, powód)."""
    slot = current_slot(now_utc)
    if now_utc - slot > MAX_LATE:
        return False, f"okno {slot:%Y-%m-%d %H:%M} UTC jest już za stare"
    if CSV_FILE.exists():
        with CSV_FILE.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "ok":
                    continue
                try:
                    ts = datetime.fromisoformat(row["timestamp_utc"])
                except (KeyError, ValueError):
                    continue
                if ts >= slot:
                    return False, f"pomiar dla okna {slot:%Y-%m-%d %H:%M} UTC już istnieje"
    return True, ""


def set_output(name, value):
    """Przekazuje wartość do kolejnych kroków GitHub Actions."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main():
    now_utc = datetime.now(timezone.utc)
    if "--force" not in sys.argv:
        due, reason = is_due(now_utc)
        if not due:
            print(f"Pomijam: {reason}")
            set_output("skipped", "true")
            return

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    CSV_FILE.parent.mkdir(exist_ok=True)
    now = now_utc.isoformat(timespec="seconds")
    errors = 0

    f, writer = open_csv()
    with f:
        for p in products:
            row = {
                "timestamp_utc": now,
                "product_id": p["id"],
                "model": p["model"],
                "vram_gb": p["vram_gb"],
                "shop": p.get("shop") or shop_from_url(p["url"]),
                "price": "", "currency": "", "status": "ok",
                "url": p["url"],
            }
            try:
                row["price"], row["currency"] = fetch_price(p["url"], p.get("selector"))
                print(f"{p['id']}: {row['price']} {row['currency']}")
            except Exception as e:  # błędy też zapisujemy, żeby widzieć luki
                row["status"] = f"error: {e}"[:200]
                errors += 1
                print(f"{p['id']}: {row['status']}", file=sys.stderr)
            writer.writerow(row)

    sys.exit(1 if errors == len(products) else 0)


if __name__ == "__main__":
    main()
