"""Génère le dashboard Grafana « Climat intérieur ».

Les capteurs sont découverts automatiquement : toute entité HA nommée « Température <pièce> »
(sensor.temperature_<pièce>_{temperature,humidity|humidite,battery|batterie}) apparaît sans modifier ce script,
y compris quand HA préfixe l'entity_id par la zone (sensor.<zone>_temperature_<pièce>_…).

Usage : python3 build_climat_interieur.py dash.json && curl -u admin:… -H "Content-Type: application/json" \
        -X POST http://localhost:3000/api/dashboards/db --data-binary @dash.json
"""
import json, sys

DS = {"type": "influxdb", "uid": "deyz7mimdfc3kd"}

# Suffixes Zigbee2MQTT (anglais) et Matter (français)
TEMP = "temperature"
HUM = "humidity|humidite"
BATT = "battery|batterie"


def q_rooms(suffix, start="v.timeRangeStart", agg=True):
    """Une série par pièce, nommée d'après l'entity_id (« Salon 1er »)."""
    window = "  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)\n" if agg else "  |> last()\n"
    return (
        'import "strings"\n'
        'import "regexp"\n'
        'from(bucket: "Homeassistant")\n'
        f"  |> range(start: {start}, stop: v.timeRangeStop)\n"
        f'  |> filter(fn: (r) => r._field == "value" and r.entity_id =~ /^(.+_)?temperature_.+_({suffix})$/)\n'
        # Matter : la tension et le type de batterie finissent aussi par « _batterie »
        '  |> filter(fn: (r) => r.entity_id !~ /_de(_la)?_batterie$/)\n'
        f"{window}"
        "  |> map(fn: (r) => {\n"
        f'      room = strings.replaceAll(v: regexp.replaceAllString(r: /^(?:.*_)?temperature_(.+)_(?:{suffix})$/, v: r.entity_id, t: "\\${{1}}"), t: "_", u: " ")\n'
        "      return {_time: r._time, _value: float(v: r._value),\n"
        "              _field: strings.toUpper(v: strings.substring(v: room, start: 0, end: 1)) + strings.substring(v: room, start: 1, end: strings.strlen(v: room))}\n"
        "  })\n"
        '  |> group(columns: ["_field"])'
    )


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


def stat(title, query, unit, decimals=1, thresholds=None):
    return {
        "type": "stat", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": thresholds},
        }, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "value", "graphMode": "none", "textMode": "value_and_name",
                    "justifyMode": "center", "orientation": "vertical"},
    }


def ts(title, query, unit):
    return {
        "type": "timeseries", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": 1, "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 0, "showPoints": "never",
                       "lineInterpolation": "smooth", "spanNulls": 3600000},
        }, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "right", "calcs": ["min", "mean", "max", "lastNotNull"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


# Sur 7 jours pour ne pas perdre les capteurs sur pile qui n'envoient qu'au changement de valeur
add(stat("Température actuelle", q_rooms(TEMP, start="-7d", agg=False), "celsius", thresholds=[
    {"color": "blue", "value": None}, {"color": "green", "value": 18},
    {"color": "orange", "value": 24}, {"color": "red", "value": 27}]), 24, 5, 0)
y[0] += 5
add(stat("Humidité actuelle", q_rooms(HUM, start="-7d", agg=False), "percent", decimals=0, thresholds=[
    {"color": "orange", "value": None}, {"color": "green", "value": 40},
    {"color": "blue", "value": 60}, {"color": "red", "value": 70}]), 24, 5, 0)
y[0] += 5
add(ts("Température", q_rooms(TEMP), "celsius"), 24, 9, 0)
y[0] += 9
add(ts("Humidité", q_rooms(HUM), "percent"), 24, 9, 0)
y[0] += 9
add(stat("Batterie des capteurs", q_rooms(BATT, start="-7d", agg=False), "percent", decimals=0, thresholds=[
    {"color": "red", "value": None}, {"color": "orange", "value": 20}, {"color": "green", "value": 40}]), 24, 4, 0)
y[0] += 4

dash = {
    "uid": "climat-interieur",
    "title": "Climat intérieur",
    "tags": ["chauffage", "temperature", "humidite"],
    "timezone": "browser",
    "refresh": "5m",
    "time": {"from": "now-7d", "to": "now"},
    "schemaVersion": 39,
    "editable": True,
    "panels": panels,
}
json.dump({"dashboard": dash, "overwrite": True, "folderUid": "",
           "message": "Dashboard climat intérieur (température, humidité, batterie par pièce)"},
          open(sys.argv[1], "w"), ensure_ascii=False, indent=2)
print(len(panels), "panneaux")
