"""Generuje wykresy do katalogu charts/ (uruchamiane w GitHub Action).

charts/all.png            - wszystkie karty na jednym wykresie
charts/<model>.png        - jeden model, porównanie sklepów
"""
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from charts_common import draw_chart  # noqa: E402

CSV = Path("data/prices.csv")
OUT = Path("charts")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def draw(df, title, path):
    fig = draw_chart(df, title)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"Zapisano {path}")


def main():
    if not CSV.exists():
        raise SystemExit("Brak data/prices.csv")
    df = pd.read_csv(CSV, parse_dates=["timestamp_utc"])
    df = df[df["status"] == "ok"].copy()
    if df.empty:
        raise SystemExit("Brak poprawnych pomiarów - pomijam wykresy.")

    df["label"] = (df["model"] + " " + df["vram_gb"].astype(str) + "GB ("
                   + df["shop"] + ")")
    OUT.mkdir(exist_ok=True)

    draw(df, "Historia cen - wszystkie karty", OUT / "all.png")
    for (model, vram), g in df.groupby(["model", "vram_gb"]):
        draw(g, f"{model} {vram}GB - porównanie sklepów",
             OUT / f"{slug(model)}-{vram}gb.png")


if __name__ == "__main__":
    main()
