import re


def parse_price(text):
    """'2 499,00 zł' / '2,499.00' / '2499' -> 2499.0"""
    text = str(text).replace("\xa0", " ").replace("\u202f", " ")
    m = re.search(r"\d[\d\s.,]*", text)
    if not m:
        raise ValueError(f"Nie znaleziono ceny w: {text!r}")
    num = re.sub(r"\s", "", m.group(0)).strip(".,")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")
    return float(num)
