"""Pobieranie list produktów z kategorii Morele.net (z paginacją).

Test z wiersza poleceń (nic nie zapisuje do CSV):
    python morele.py "https://www.morele.net/kategoria/karty-graficzne-12/,,,,,,,,0,,,,8143O2261060/1/"
    python morele.py "<url>" --html strona.html    # zapisz też pierwszą stronę HTML
"""
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from pricing import parse_price

BASE = "https://www.morele.net"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

# link produktu: /karta-graficzna-...-15418243/
PRODUCT_HREF = re.compile(r"/karta-graficzna-[a-z0-9\-]*?-(\d{5,9})/?(?:[?#].*)?$")
MODEL_RE = re.compile(r"RTX\s*(50[5-9]0)(?:\s+(Ti)\b)?(?:\s+(Super)\b)?", re.I)
VRAM_RE = re.compile(r"\b(\d{1,2})\s*G(?:B)?\b", re.I)
PRICE_RE = re.compile(
    r"(\d{1,3}(?:[ \u00a0\u202f]\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*zł"
)
# klasy, które zwykle oznaczają cenę przekreśloną / ratę / inne niż główna
SKIP_CLASS = re.compile(r"old|stara|rata|install|lowest|omnibus|saving|discount", re.I)


def _norm(text):
    return re.sub(r"[\s\u00a0\u202f]+", " ", text).strip()


def describe(title):
    """Z tytułu oferty wyciąga nazwę, model (np. 'RTX 5070 Ti') i VRAM. None = to nie RTX 50."""
    name = re.sub(r"^\s*Karta graficzna\s+", "", _norm(title))
    m = MODEL_RE.search(name)
    if not m:
        return None
    model = "RTX " + m.group(1) + (" Ti" if m.group(2) else "") + (
        " Super" if m.group(3) else "")
    v = VRAM_RE.search(name)
    return {"name": name, "model": model, "vram_gb": int(v.group(1)) if v else ""}


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _jsonld_prices(soup):
    """Jeśli lista ma dane schema.org (Product + Offer), to są najpewniejsze."""
    out = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk(data):
            url = node.get("url")
            offers = node.get("offers")
            if not (isinstance(url, str) and offers):
                continue
            m = PRODUCT_HREF.search(url)
            if not m:
                continue
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offer, dict):
                raw = offer.get("price") or offer.get("lowPrice")
                if raw is not None:
                    try:
                        out[m.group(1)] = parse_price(raw)
                    except ValueError:
                        pass
    return out


def _find_card(anchor):
    """Największy element zawierający linki tylko do jednego produktu."""
    best, node = anchor, anchor
    while node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
        parent = node.parent
        ids = {PRODUCT_HREF.search(a["href"]).group(1)
               for a in parent.find_all("a", href=PRODUCT_HREF)}
        if len(ids) > 1:
            break
        best, node = parent, parent
    return best


PREFER_CLASS = re.compile(r"new|current|final|main|actual|promo", re.I)


def _card_price(card):
    # tylko "liście": elementy z ceną, które nie zawierają w środku innych elementów z ceną
    # (zewnętrzny kontener mógłby zawierać obie ceny - starą i nową)
    leaves = [el for el in card.select('[class*="price" i]')
              if not el.select('[class*="price" i]')]
    leaves = [el for el in leaves if not SKIP_CLASS.search(" ".join(el.get("class", [])))]
    # najpierw elementy wyglądające na cenę aktualną, potem pozostałe
    leaves.sort(key=lambda el: not PREFER_CLASS.search(" ".join(el.get("class", []))))
    for el in leaves:
        m = PRICE_RE.search(_norm(el.get_text("")))
        if m:
            return parse_price(m.group(1))
    # awaryjnie: pierwszy "x zł" w tekście karty, po wycięciu rat i "N propozycji od ..."
    text = _norm(card.get_text(" ")).replace(" ,", ",")
    text = re.sub(r"rata od\s*[\d\s,]+zł", "", text, flags=re.I)
    text = re.sub(r"\d+\s+propozycj\w*\s+od\s*[\d\s,]+zł", "", text, flags=re.I)
    m = PRICE_RE.search(text)
    return parse_price(m.group(1)) if m else None


def parse_listing(html, base=BASE):
    """HTML strony listy -> [{'id','url','name','model','vram_gb','price'}] (tylko RTX 50)."""
    soup = BeautifulSoup(html, "html.parser")
    ld_prices = _jsonld_prices(soup)

    anchors = {}
    for a in soup.find_all("a", href=PRODUCT_HREF):
        pid = PRODUCT_HREF.search(a["href"]).group(1)
        text = a.get_text(" ", strip=True)
        if not text:
            img = a.find("img")
            text = (img.get("alt") or "").strip() if img else ""
        if not text:
            text = a.get("title", "")
        entry = anchors.setdefault(
            pid, {"url": urljoin(base, a["href"]), "title": "", "anchor": a})
        if len(text) > len(entry["title"]):
            entry["title"] = text

    items = []
    for pid, e in anchors.items():
        info = describe(e["title"])
        if not info:
            continue
        price = ld_prices.get(pid)
        if price is None:
            price = _card_price(_find_card(e["anchor"]))
        if price is None:
            print(f"  ! brak ceny: {info['name'][:60]}", file=sys.stderr)
            continue
        items.append({"id": pid, "url": e["url"], "price": price, **info})
    return items


def page_url(url, n):
    """Lista w Morele ma numer strony na końcu adresu: .../8143O2261060/1/"""
    return re.sub(r"/\d+/?$", f"/{n}/", url)


def scrape_listing(url, delay=1.5, max_pages=15):
    session = requests.Session()
    session.headers.update(HEADERS)
    found = {}
    for n in range(1, max_pages + 1):
        r = session.get(page_url(url, n), timeout=30)
        if r.status_code == 404 and n > 1:
            break
        r.raise_for_status()
        new = [i for i in parse_listing(r.text) if i["id"] not in found]
        if not new:
            break
        for i in new:
            found[i["id"]] = i
        time.sleep(delay)
    return list(found.values())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    url = sys.argv[1]
    if "--html" in sys.argv:
        path = sys.argv[sys.argv.index("--html") + 1]
        r = requests.get(page_url(url, 1), headers=HEADERS, timeout=30)
        open(path, "w", encoding="utf-8").write(r.text)
        print(f"Zapisano {path} (HTTP {r.status_code}, {len(r.text)} znaków)")
    items = scrape_listing(url)
    for i in items:
        print(f"{i['price']:>9.2f}  {i['model']:<14} {i['vram_gb']!s:>3}GB  {i['name'][:70]}")
    print(f"Razem: {len(items)}")
