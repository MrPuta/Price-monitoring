import pandas as pd

df = pd.read_csv("data/prices.csv", parse_dates=["timestamp_utc"])
df = df[df["status"] == "ok"]

# tabela: wiersze = czas, kolumny = produkty
pivot = df.pivot_table(index="timestamp_utc", columns="product", values="price")
print(pivot.tail())

# najniższa cena i zmiana względem pierwszego pomiaru
print(pivot.min())
print((pivot.iloc[-1] / pivot.iloc[0] - 1) * 100)
