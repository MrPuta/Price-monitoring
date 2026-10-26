"""Wspólne rysowanie wykresów dla plot_prices.py i generate_charts.py."""
import math

import matplotlib.pyplot as plt

TZ = "Europe/Warsaw"
MAX_LABELS = 20  # tyle podpisów na osi X maksymalnie, żeby się nie zlewały


def add_label(df):
    """Etykieta serii: pełna nazwa produktu, a gdy jej brak - model + VRAM + sklep."""
    fallback = df["model"] + " " + df["vram_gb"].astype(str) + "GB (" + df["shop"] + ")"
    if "name" in df:
        name = df["name"].fillna("").astype(str)
        df["label"] = name.where(name != "", fallback)
    else:
        df["label"] = fallback
    return df


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

    # kolejność serii = kolejność ostatnich cen (od najdroższej), żeby legenda
    # odpowiadała kolejności linii na prawym brzegu wykresu
    last = df.sort_values("x").groupby("label")["price"].last().sort_values(ascending=False)
    labels = list(last.index)
    n_series = len(labels)

    fig, ax = plt.subplots(figsize=(14 if n_series > 12 else 11, 6 if n_series > 12 else 5.5))
    if n_series > 10:  # więcej kolorów + zmiana stylu linii, żeby serie dało się odróżnić
        colors = list(plt.cm.tab20.colors)
        styles = ["-", "--", ":"]
    else:
        colors = [f"C{i}" for i in range(10)]
        styles = ["-"]
    for i, label in enumerate(labels):
        g = df[df["label"] == label].sort_values("x")
        ax.plot(g["x"], g["price"], marker="o", markersize=3.5, linewidth=1.3,
                color=colors[i % len(colors)],
                linestyle=styles[(i // len(colors)) % len(styles)], label=label)

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
    if n_series > 12:  # dużo serii: legenda poza wykresem, drobnym drukiem
        ax.legend(fontsize=6, loc="upper left", bbox_to_anchor=(1.01, 1),
                  ncol=1 if n_series <= 40 else 2)
    else:
        ax.legend(fontsize=8)
    fig.tight_layout()
    return fig
