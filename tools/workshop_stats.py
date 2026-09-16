#!/usr/bin/env python3
"""
Coleta as metricas do item na Oficina e acumula historico.

A API da Steam devolve so uma foto do momento (views, subscriptions,
favorited). A aba Item Stats mostra grafico mas nao exporta, e nao ha endpoint
de serie historica. Entao a serie e construida aqui: cada execucao anexa uma
linha ao CSV e mostra a variacao desde a foto anterior.

Uso:
    .venv/bin/python tools/workshop_stats.py          # coleta e mostra
    .venv/bin/python tools/workshop_stats.py --show   # so mostra o historico
"""
import csv
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

WORKSHOP_ID = "3795522820"
REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "tools/workshop_stats.csv"

FIELDS = ["views", "subscriptions", "favorited",
          "lifetime_subscriptions", "lifetime_favorited"]
COLUMNS = ["timestamp"] + FIELDS + ["file_size", "title"]

API = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"


def fetch():
    body = urllib.parse.urlencode(
        {"itemcount": 1, "publishedfileids[0]": WORKSHOP_ID}).encode()
    with urllib.request.urlopen(API, data=body, timeout=20) as r:
        data = json.load(r)
    item = data["response"]["publishedfiledetails"][0]
    if item.get("result") != 1:
        sys.exit(f"a API nao devolveu o item (result={item.get('result')}). "
                 "Item privado ou id errado?")
    return item


def read_history():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append(item):
    row = {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
           "file_size": item.get("file_size", ""),
           "title": item.get("title", "")}
    for k in FIELDS:
        row[k] = item.get(k, 0)

    novo = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if novo:
            w.writeheader()
        w.writerow(row)
    return row


def show(history):
    if not history:
        print("sem historico ainda.")
        return

    print(f"{'quando':<17} {'views':>7} {'inscritos':>10} {'favoritos':>10}")
    print("-" * 48)
    anterior = None
    for row in history[-15:]:
        quando = row["timestamp"].replace("T", " ")[5:16]

        def cell(k, largura):
            atual = int(row[k])
            if anterior is None:
                return f"{atual:>{largura}}"
            delta = atual - int(anterior[k])
            marca = f" (+{delta})" if delta > 0 else ""
            return f"{str(atual) + marca:>{largura}}"

        print(f"{quando:<17} {cell('views', 7)} "
              f"{cell('subscriptions', 10)} {cell('favorited', 10)}")
        anterior = row

    primeira, ultima = history[0], history[-1]
    if len(history) > 1:
        t0 = dt.datetime.fromisoformat(primeira["timestamp"])
        t1 = dt.datetime.fromisoformat(ultima["timestamp"])
        horas = max((t1 - t0).total_seconds() / 3600, 1e-9)
        print()
        print(f"janela: {horas:.1f}h desde a primeira coleta")
        for k, rotulo in [("views", "visitas"),
                          ("subscriptions", "inscritos"),
                          ("favorited", "favoritos")]:
            ganho = int(ultima[k]) - int(primeira[k])
            print(f"  {rotulo:<10} +{ganho:<5} ({ganho / horas:.1f}/h)")


def main():
    if "--show" in sys.argv:
        show(read_history())
        return

    item = fetch()
    anterior = read_history()
    row = append(item)

    print(f"coletado: {row['timestamp']}")
    for k in FIELDS:
        atual = int(row[k])
        if anterior:
            delta = atual - int(anterior[-1][k])
            marca = f"  ({delta:+d} desde a ultima coleta)" if delta else ""
        else:
            marca = ""
        print(f"  {k:<24} {atual}{marca}")
    print(f"\nhistorico: {CSV_PATH}  ({len(anterior) + 1} coletas)")


if __name__ == "__main__":
    main()
