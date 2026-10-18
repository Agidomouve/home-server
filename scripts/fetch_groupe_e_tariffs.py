"""Écrit les tarifs Groupe E (Double, Vario) dans InfluxDB, prix de demain compris.

Usage : python3 -I fetch_groupe_e_tariffs.py <ha_config_dir> [--from AAAA-MM-JJ]
Par défaut : d'hier à après-demain. --from 2026-01-01 pour importer l'historique (l'API remonte au 01.01.2026).
Mesure « groupe_e_tarif », tag tariff (double|vario), champs price / grid / price_ht en CHF/kWh.
price = integrated × TVA, comme l'intégration sgr_dyntariff de HA (sensor.groupee_*).
Réécrire un créneau écrase la valeur : on peut relancer sans risque.
"""
import datetime as dt, json, re, sys, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

HA = sys.argv[1]
ORG, BUCKET = "MaisonRussy", "Homeassistant"
URL = "http://localhost:8086"
API = "https://api.tariffs.groupe-e.ch/v2/tariffs"
TARIFFS = ("double", "vario")
VAT = 1.081
TZ = ZoneInfo("Europe/Zurich")
CHUNK = dt.timedelta(days=7)

token = re.search(r"^influxdb_token:\s*(\S+)", open(f"{HA}/secrets.yaml").read(), re.M).group(1)

today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
start = today - dt.timedelta(days=1)
if "--from" in sys.argv:
    start = dt.datetime.fromisoformat(sys.argv[sys.argv.index("--from") + 1]).replace(tzinfo=TZ)
end = today + dt.timedelta(days=2)


def fetch(tariff, t0, t1):
    q = urllib.parse.urlencode({"tariff_name": tariff, "start_timestamp": t0.isoformat(), "end_timestamp": t1.isoformat()})
    with urllib.request.urlopen(f"{API}?{q}", timeout=60) as r:
        return json.load(r)["prices"]


lines = []
for tariff in TARIFFS:
    n, last = 0, None
    t0 = start
    while t0 < end:
        t1 = min(t0 + CHUNK, end)
        for p in fetch(tariff, t0, t1):
            ts = int(dt.datetime.fromisoformat(p["start_timestamp"]).timestamp())
            ht = p["integrated"][0]["value"]
            grid = p["grid"][0]["value"]
            lines.append(f"groupe_e_tarif,tariff={tariff} price={round(ht * VAT, 5)},grid={round(grid * VAT, 5)},price_ht={ht} {ts}")
            n, last = n + 1, p["start_timestamp"]
        t0 = t1
    print(f"{tariff} : {n} créneaux, dernier {last}")

hdr = {"Authorization": f"Token {token}", "Content-Type": "text/plain; charset=utf-8"}
url = f"{URL}/api/v2/write?org={ORG}&bucket={BUCKET}&precision=s"
for i in range(0, len(lines), 5000):
    req = urllib.request.Request(url, data="\n".join(lines[i:i + 5000]).encode(), headers=hdr, method="POST")
    urllib.request.urlopen(req, timeout=60).close()
print(f"{len(lines)} points écrits")
