"""Wspólne rysowanie wykresów dla plot_prices.py i generate_charts.py."""
import math

import matplotlib.pyplot as plt

TZ = "Europe/Warsaw"
MAX_LABELS = 20  # tyle podpisów na osi X maksymalnie, żeby się nie zlewały


def draw_chart(df, title):
    """Oś X = kolejne pomiary (jeden punkt na każdy pomiar), podpisane godziną pomiaru.

    Odstępy między punktami są równe, niezależnie od tego, ile czasu minęło
    między pomiarami. Podpisy to czas polski.
    """
    df = df.copy()
    df["ts"] = df["timestamp_utc"].dt.tz_convert(TZ)

    stamps = df["ts"].drop_duplicates().sort_values().reset_index(drop=True)
    position = {t: i for i, t in enumerate(stamps)}
    df["x"] = df["ts"].map(position)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for label, g in df.groupby("label"):
        g = g.sort_values("x")
        ax.plot(g["x"], g["price"], marker="o", markersize=4, label=label)

    # podpisy: przy małej liczbie pomiarów każdy, przy dużej co n-ty
    step = max(1, math.ceil(len(stamps) / MAX_LABELS))
    ticks = list(range(0, len(stamps), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels(stamps.dt.strftime("%d.%m %H:%M").iloc[ticks],
                       rotation=45, ha="right")
    ax.set_xlim(-0.5, max(len(stamps) - 0.5, 0.5))

    ax.set_xlabel("Czas pomiaru (czas polski)")
    ax.set_ylabel(f"Cena ({df['currency'].iloc[0]})")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig
