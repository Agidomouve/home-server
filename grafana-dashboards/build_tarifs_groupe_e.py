"""Génère le dashboard Grafana « Tarifs Groupe E » (Double et Vario, prix de demain compris).

Données : mesure groupe_e_tarif écrite par scripts/fetch_groupe_e_tariffs.py (tag tariff, champs price/grid, TTC).
Le coût comparé utilise le soutirage réseau (smart_meter_ts_65a_3_energie_reelle_consommee) au pas horaire.

Usage : python3 build_tarifs_groupe_e.py dash.json && curl -u admin:… -H "Content-Type: application/json" \
        -X POST http://localhost:3000/api/dashboards/db --data-binary @dash.json
"""
import json, sys

DS = {"type": "influxdb", "uid": "deyz7mimdfc3kd"}
NAMES = '["double": "Double", "vario": "Vario"]'
METER = "smart_meter_ts_65a_3_energie_reelle_consommee"
COLORS = {"Double": "blue", "Vario": "orange"}

HEAD = (
    'import "date"\n'
    'import "dict"\n'
    'import "timezone"\n'
    'option location = timezone.location(name: "Europe/Zurich")\n'
    f"names = {NAMES}\n"
    "d0 = date.truncate(t: now(), unit: 1d)\n"
)


def prices(field="price", start="v.timeRangeStart", stop="v.timeRangeStop", tariff=None):
    t = f' and r.tariff == "{tariff}"' if tariff else ""
    return (
        'from(bucket: "Homeassistant")\n'
        f"  |> range(start: {start}, stop: {stop})\n"
        f'  |> filter(fn: (r) => r._measurement == "groupe_e_tarif" and r._field == "{field}"{t})\n'
    )


def named(extra=""):
    return (f"  |> map(fn: (r) => ({{_time: r._time, _value: r._value{extra}, "
            '_field: dict.get(dict: names, key: r.tariff, default: r.tariff)}))\n'
            '  |> group(columns: ["_field"])')


def q_series(field="price", suffix=""):
    return HEAD + prices(field) + named().replace("default: r.tariff)", f'default: r.tariff) + "{suffix}"')


def q_now(tariff):
    return HEAD + prices(start="-1d", stop="now()", tariff=tariff) + "  |> last()"


def q_day(tariff, fn, day=0):
    return (HEAD + prices(start=f"date.add(d: {day}d, to: d0)", stop=f"date.add(d: {day + 1}d, to: d0)", tariff=tariff)
            + f"  |> {fn}()")


def q_cheapest(tariff, day=1):
    """Heure locale du créneau le moins cher (« 14:30 »)."""
    two = '(if date.{0}(t: r._time) < 10 then "0" else "") + string(v: date.{0}(t: r._time))'
    return (q_day(tariff, "min", day) + "\n"
            f'  |> map(fn: (r) => ({{_value: {two.format("hour")} + ":" + {two.format("minute")}}}))')


def q_cost(every="1d", total=False):
    """Coût du soutirage réseau à chaque tarif : kWh horaires × prix moyen de l'heure."""
    tail = ("  |> sum()\n  |> map(fn: (r) => ({_time: now(), _value: r._value, _field: r._field}))\n" if total else
            f"  |> aggregateWindow(every: {every}, fn: sum, createEmpty: false)\n")
    return (
        HEAD
        + 'energy = from(bucket: "Homeassistant")\n'
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        f'  |> filter(fn: (r) => r._field == "value" and r.entity_id == "{METER}")\n'
        "  |> aggregateWindow(every: 1h, fn: last, createEmpty: false)\n"
        "  |> difference(nonNegative: true)\n"
        "  |> group()\n"
        "  |> map(fn: (r) => ({_time: r._time, kwh: float(v: r._value) / 1000.0}))\n"
        "price = " + prices().lstrip()
        + "  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)\n"
        "  |> group()\n"
        "  |> map(fn: (r) => ({_time: r._time, tariff: r.tariff, p: r._value}))\n"
        'join(tables: {e: energy, p: price}, on: ["_time"])\n'
        "  |> map(fn: (r) => ({_time: r._time, _value: r.kwh * r.p, _field: dict.get(dict: names, key: r.tariff, default: r.tariff)}))\n"
        '  |> group(columns: ["_field"])\n'
        + tail
    ).rstrip("\n")


def q_saving():
    """Double − Vario sur la période : positif = le Vario aurait coûté moins cher (rouge sinon)."""
    return (q_cost(total=True) + "\n"
            '  |> group()\n'
            '  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
            '  |> map(fn: (r) => ({_time: r._time, _value: r.Double - r.Vario}))')


def q_by_hour():
    """Prix moyen par heure de la journée (heure suisse), pour repérer les heures creuses du Vario."""
    return (HEAD + prices()
            + '  |> map(fn: (r) => ({r with hour: (if date.hour(t: r._time) < 10 then "0" else "") + string(v: date.hour(t: r._time)) + "h"}))\n'
            '  |> group(columns: ["tariff", "hour"])\n'
            "  |> mean()\n"
            "  |> group()\n"
            '  |> map(fn: (r) => ({hour: r.hour, _value: r._value, tariff: dict.get(dict: names, key: r.tariff, default: r.tariff)}))\n'
            '  |> pivot(rowKey: ["hour"], columnKey: ["tariff"], valueColumn: "_value")\n'
            '  |> sort(columns: ["hour"])')


panels = []
pid = [0]
y = [0]


def add(p, w, h, x):
    pid[0] += 1
    p["id"] = pid[0]
    p["datasource"] = DS
    p["gridPos"] = {"x": x, "y": y[0], "w": w, "h": h}
    for i, t in enumerate(p.get("targets", [])):
        t.setdefault("refId", chr(65 + i))
        t["datasource"] = DS
    panels.append(p)


def row(title):
    pid[0] += 1
    panels.append({"type": "row", "title": title, "id": pid[0], "collapsed": False,
                   "gridPos": {"x": 0, "y": y[0], "w": 24, "h": 1}, "panels": []})
    y[0] += 1


def color_overrides():
    return [{"matcher": {"id": "byRegexp", "options": f"^{k}.*"},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": v}}]} for k, v in COLORS.items()]


def stat(title, query, unit="currencyCHF", decimals=4, color="blue", time_from=None):
    p = {
        "type": "stat", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "color": {"mode": "fixed", "fixedColor": color},
        }, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/" if unit == "string" else "", "values": False},
                    "colorMode": "value", "graphMode": "none", "textMode": "value", "justifyMode": "center"},
    }
    if time_from:
        p["timeFrom"] = time_from
    return p


def ts(title, query, unit="currencyCHF", fill=10, draw="line", interp="stepAfter", time_from=None, overrides=None):
    p = {
        "type": "timeseries", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": 4, "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": draw, "lineWidth": 2, "fillOpacity": fill, "showPoints": "never",
                       "lineInterpolation": interp, "spanNulls": 3600000, "barAlignment": -1},
        }, "overrides": color_overrides() + (overrides or [])},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "min", "max"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }
    if time_from:
        p["timeFrom"] = time_from
    return p


def bars(title, query, every, time_from, decimals=2):
    p = ts(title, query, fill=80, draw="bars", time_from=time_from)
    p["fieldConfig"]["defaults"]["decimals"] = decimals
    p["options"]["legend"]["calcs"] = ["sum", "mean"]
    p["interval"] = every
    return p


# ------------------------------------------------------------------ Maintenant
row("Maintenant et demain")
add(stat("Vario maintenant", q_now("vario"), color=COLORS["Vario"]), 4, 4, 0)
add(stat("Double maintenant", q_now("double"), color=COLORS["Double"]), 4, 4, 4)
add(stat("Vario moyen aujourd'hui", q_day("vario", "mean"), color=COLORS["Vario"]), 4, 4, 8)
add(stat("Vario min demain", q_day("vario", "min", 1), color="green"), 4, 4, 12)
add(stat("Créneau le moins cher demain", q_cheapest("vario"), unit="string", color="green"), 4, 4, 16)
add(stat("Vario max demain", q_day("vario", "max", 1), color="red"), 4, 4, 20)
y[0] += 4
dashed = [{"matcher": {"id": "byRegexp", "options": ".*réseau$"},
           "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                          {"id": "custom.fillOpacity", "value": 0}, {"id": "custom.lineWidth", "value": 1}]}]
p = ts("Prix TTC par créneau de 15 min (aujourd'hui et demain)", q_series(), overrides=dashed)
p["targets"].append({"query": q_series("grid", " réseau")})
add(p, 24, 10, 0)
y[0] += 10

# ------------------------------------------------------------------ Comparaison
row("Double ou Vario ? (soutirage réseau réel)")
add(bars("Coût par jour", q_cost("1d"), "1d", "30d"), 16, 8, 0)
add(stat("Coût Double (30 j)", q_cost(total=True).replace("|> sum()", '|> sum()\n  |> filter(fn: (r) => r._field == "Double")'),
         decimals=2, color=COLORS["Double"], time_from="30d"), 4, 4, 16)
add(stat("Coût Vario (30 j)", q_cost(total=True).replace("|> sum()", '|> sum()\n  |> filter(fn: (r) => r._field == "Vario")'),
         decimals=2, color=COLORS["Vario"], time_from="30d"), 4, 4, 20)
y[0] += 4
for title, tf, x in (("Gain Vario vs Double (30 j)", "30d", 16), ("Gain Vario vs Double (depuis janvier)", "now/y", 20)):
    p = stat(title, q_saving(), decimals=2, time_from=tf)
    p["fieldConfig"]["defaults"]["color"] = {"mode": "thresholds"}
    p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 0}]}
    add(p, 4, 4, x)
y[0] += 4
add(bars("Coût par mois", q_cost("1mo"), "1mo", "now/y"), 12, 8, 0)
hours = {
    "type": "barchart", "title": "Prix moyen par heure (30 derniers jours)",
    "targets": [{"query": q_by_hour()}],
    "timeFrom": "30d",
    "fieldConfig": {"defaults": {"unit": "currencyCHF", "decimals": 3, "color": {"mode": "palette-classic"},
                                 "custom": {"fillOpacity": 80, "lineWidth": 0}},
                    "overrides": color_overrides()},
    "options": {"xField": "hour", "orientation": "vertical", "groupWidth": 0.8, "barWidth": 0.9,
                "showValue": "never", "legend": {"displayMode": "list", "placement": "bottom"},
                "tooltip": {"mode": "multi"}},
}
add(hours, 12, 8, 12)
y[0] += 8

dash = {
    "uid": "tarifs-groupe-e",
    "title": "Tarifs Groupe E",
    "tags": ["energie", "tarif"],
    "timezone": "browser",
    "refresh": "5m",
    "time": {"from": "now/d", "to": "now+1d/d"},
    "schemaVersion": 39,
    "editable": True,
    "panels": panels,
}
json.dump({"dashboard": dash, "overwrite": True, "folderUid": "",
           "message": "Dashboard tarifs Groupe E (Double, Vario, prix de demain)"},
          open(sys.argv[1], "w"), ensure_ascii=False, indent=2)
print(len(panels), "panneaux")
