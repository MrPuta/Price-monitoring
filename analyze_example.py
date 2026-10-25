import pandas as pd

df = pd.read_csv("data/prices.csv", parse_dates=["timestamp_utc"])
df = df[df["status"] == "ok"]

# tabela: wiersze = czas, kolumny = produkty (łatwe porównanie wielu kart)
pivot = df.pivot_table(index="timestamp_utc", columns="product_id", values="price")
print(pivot.tail())

# najniższa cena w historii i zmiana od pierwszego pomiaru (%)
print(pivot.min())
print(((pivot.iloc[-1] / pivot.iloc[0] - 1) * 100).round(1))

# średnia cena danego modelu w podziale na sklepy
print(df.groupby(["model", "shop"])["price"].agg(["min", "mean", "max"]).round(0))
