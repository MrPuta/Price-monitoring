"""Wykres historii cen z data/prices.csv.

Przykłady:
  python plot_prices.py                                  # wszystkie karty
  python plot_prices.py --id rtx4070s-asus-dual          # jedna pozycja
  python plot_prices.py --model "4070"                   # wszystkie, których model zawiera "4070"
  python plot_prices.py --model "4070" --vram 12 --days 30
  python plot_prices.py --shop x-kom --out x-kom.png
  python plot_prices.py --show                           # otwórz okno zamiast tylko zapisu PNG
"""
import argparse

import matplotlib

import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--csv", default="data/prices.csv")
parser.add_argument("--id", nargs="+", help="jedno lub kilka product_id")
parser.add_argument("--model", help="fragment nazwy modelu (bez wielkości liter)")
parser.add_argument("--shop", help="fragment nazwy sklepu")
parser.add_argument("--vram", type=int, help="ilość VRAM w GB")
parser.add_argument("--days", type=int, help="tylko ostatnie N dni")
parser.add_argument("--out", default="chart.png")
parser.add_argument("--show", action="store_true")
args = parser.parse_args()

if not args.show:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

df = pd.read_csv(args.csv, parse_dates=["timestamp_utc"])
df = df[df["status"] == "ok"].copy()

if args.id:
    df = df[df["product_id"].isin(args.id)]
if args.model:
    df = df[df["model"].str.contains(args.model, case=False, na=False)]
if args.shop:
    df = df[df["shop"].str.contains(args.shop, case=False, na=False)]
if args.vram:
    df = df[df["vram_gb"] == args.vram]
if args.days:
    cutoff = df["timestamp_utc"].max() - pd.Timedelta(days=args.days)
    df = df[df["timestamp_utc"] >= cutoff]

if df.empty:
    raise SystemExit("Brak danych dla podanych filtrów.")

df["label"] = df["model"] + " " + df["vram_gb"].astype(str) + "GB (" + df["shop"] + ")"

fig, ax = plt.subplots(figsize=(11, 5.5))
for label, g in df.groupby("label"):
    g = g.sort_values("timestamp_utc")
    ax.plot(g["timestamp_utc"], g["price"], marker="o", markersize=3, label=label)

ax.set_ylabel(f"Cena ({df['currency'].iloc[0]})")
ax.set_title("Historia cen kart graficznych")
ax.grid(alpha=0.3)
ax.legend(fontsize=8)
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig(args.out, dpi=150)
print(f"Zapisano {args.out}")
if args.show:
    plt.show()
