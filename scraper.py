"""Pobiera ceny kart graficznych i dopisuje je do data/prices.csv.

Źródła danych:
  * listings.json - listy kategorii Morele.net (wszystkie karty z listy)
  * products.json - pojedyncze strony produktów (dowolny sklep)
"""
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

import morele
from pricing import parse_price

ROOT = Path(__file__).parent
PRODUCTS_FILE = ROOT / "products.json"
LISTINGS_FILE = ROOT / "listings.json"
CSV_FILE = ROOT / "data" / "prices.csv"
FIELDS = ["timestamp_utc", "product_id", "model", "vram_gb", "shop", "name",
          "price", "currency", "status", "url"]

TZ = ZoneInfo("Europe/Warsaw")
SLOT_HOURS = (8, 20)             # pomiary ok. 8:00 i 20:00 czasu polskiego
MAX_LATE = timedelta(hours=6)    # po tylu godzinach od pory pomiaru uznajemy okno za stracone

HEADERS = morele.HEADERS


# ---------- pojedyncze strony produktów ----------

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


# ---------- CSV ----------

def open_csv():
    """Otwiera CSV do dopisywania. Starszy format jest przepisany na nowy (bez utraty danych)."""
    if CSV_FILE.exists():
        with CSV_FILE.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            old_rows = list(reader) if header != FIELDS else []
        if header != FIELDS:
            with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS, restval="", extrasaction="ignore")
                w.writeheader()
                for row in old_rows:
                    row.setdefault("product_id", row.get("product", ""))
                    w.writerow(row)
            print(f"Zmieniony format CSV - przepisano {len(old_rows)} starych wierszy")
    new_file = not CSV_FILE.exists()
    f = CSV_FILE.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    if new_file:
        writer.writeheader()
    return f, writer


# ---------- okna czasowe (8:00 i 20:00 czasu polskiego) ----------

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


# ---------- zbieranie wierszy ----------

def _load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def collect_rows(now):
    """Zwraca (wiersze, liczba_źródeł, liczba_nieudanych_źródeł)."""
    rows, units, failures = [], 0, 0

    def blank(**kw):
        row = {k: "" for k in FIELDS}
        row.update(timestamp_utc=now, status="ok", **kw)
        return row

    # 1) pojedyncze produkty
    for p in (p for p in _load(PRODUCTS_FILE) if p.get("url")):
        units += 1
        row = blank(product_id=p["id"], model=p["model"], vram_gb=p["vram_gb"],
                    shop=p.get("shop") or shop_from_url(p["url"]),
                    name=p.get("name", ""), url=p["url"])
        try:
            row["price"], row["currency"] = fetch_price(p["url"], p.get("selector"))
            print(f"{p['id']}: {row['price']} {row['currency']}")
        except Exception as e:
            row["status"] = f"error: {e}"[:200]
            failures += 1
            print(f"{p['id']}: {row['status']}", file=sys.stderr)
        rows.append(row)

    # 2) listy kategorii Morele
    seen = set()
    for l in _load(LISTINGS_FILE):
        units += 1
        label = l.get("model", l["url"])
        try:
            items = morele.scrape_listing(l["url"])
            if not items:
                raise ValueError("lista jest pusta lub nie udało się jej odczytać")
        except Exception as e:
            failures += 1
            print(f"{label}: error: {e}", file=sys.stderr)
            rows.append(blank(product_id=f"listing-{label}", model=label,
                              shop=l.get("shop", "morele.net"), url=l["url"],
                              status=f"error: {e}"[:200]))
            continue
        added = 0
        for it in items:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            added += 1
            rows.append(blank(product_id=f"morele-{it['id']}", model=it["model"],
                              vram_gb=it["vram_gb"], shop=l.get("shop", "morele.net"),
                              name=it["name"], price=it["price"], currency="PLN",
                              url=it["url"]))
        print(f"{label}: {added} kart")
    return rows, units, failures


def main():
    now_utc = datetime.now(timezone.utc)
    if "--force" not in sys.argv:
        due, reason = is_due(now_utc)
        if not due:
            print(f"Pomijam: {reason}")
            set_output("skipped", "true")
            return

    now = now_utc.isoformat(timespec="seconds")
    rows, units, failures = collect_rows(now)
    if units == 0:
        print("Brak źródeł - uzupełnij listings.json lub products.json")
        set_output("skipped", "true")
        return

    CSV_FILE.parent.mkdir(exist_ok=True)
    f, writer = open_csv()
    with f:
        writer.writerows(rows)
    ok = sum(r["status"] == "ok" for r in rows)
    print(f"Zapisano {len(rows)} wierszy ({ok} poprawnych)")
    sys.exit(1 if failures == units else 0)


if __name__ == "__main__":
    main()
