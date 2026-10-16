"""Génère le dashboard Grafana « Énergie maison ».

Usage : python3 build_energie_maison.py dash.json && curl -u admin:… -H "Content-Type: application/json" \
        -X POST http://localhost:3000/api/dashboards/db --data-binary @dash.json
"""
import json, sys

DS = {"type": "influxdb", "uid": "deyz7mimdfc3kd"}


def with_tz(q):
    """Heure suisse pour les fenêtres journalières (les imports doivent précéder l'option)."""
    return 'import "timezone"\n' + q.replace('import "dict"\n', 'import "dict"\noption location = timezone.location(name: "Europe/Zurich")\n', 1)


def names_dict(d):
    return "[" + ", ".join(f'"{k}": "{v}"' for k, v in d.items()) + "]"


def q_series(names, field="value", every="v.windowPeriod", fn="mean", scale=None, extra=""):
    """Séries temporelles d'une liste d'entités, renommées avec un nom lisible."""
    regex = "|".join(names)
    sc = f" * {scale}" if scale else ""
    return (
        'import "dict"\n'
        f"names = {names_dict(names)}\n"
        'from(bucket: "Homeassistant")\n'
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        f'  |> filter(fn: (r) => r._field == "{field}" and r.entity_id =~ /^({regex})$/)\n'
        f"{extra}"
        f"  |> aggregateWindow(every: {every}, fn: {fn}, createEmpty: false)\n"
        f"  |> map(fn: (r) => ({{_time: r._time, _value: float(v: r._value){sc}, _field: dict.get(dict: names, key: r.entity_id, default: r.entity_id)}}))\n"
        '  |> group(columns: ["_field"])'
    )


def q_last(entity, scale=None):
    sc = f" * {scale}" if scale else ""
    return (
        'from(bucket: "Homeassistant")\n'
        "  |> range(start: -30d)\n"
        f'  |> filter(fn: (r) => r._field == "value" and r.entity_id == "{entity}")\n'
        "  |> last()\n"
        f"  |> map(fn: (r) => ({{_time: r._time, _value: float(v: r._value){sc}}}))"
    )


def q_daily_max(names, scale=None):
    """Compteurs remis à zéro chaque jour : max par jour (heure suisse)."""
    return with_tz(q_series(names, every="1d", fn="max", scale=scale))


def q_increase(names, scale=None):
    """Énergie consommée sur la période à partir d'un compteur cumulatif."""
    regex = "|".join(names)
    sc = f" * {scale}" if scale else ""
    return (
        'import "dict"\n'
        f"names = {names_dict(names)}\n"
        'from(bucket: "Homeassistant")\n'
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        f'  |> filter(fn: (r) => r._field == "value" and r.entity_id =~ /^({regex})$/)\n'
        "  |> increase()\n"
        "  |> last()\n"
        f"  |> map(fn: (r) => ({{_time: r._time, _value: r._value{sc}, _field: dict.get(dict: names, key: r.entity_id, default: r.entity_id)}}))\n"
        '  |> group(columns: ["_field"])'
    )


def q_daily_increase(names, scale=None):
    regex = "|".join(names)
    sc = f" * {scale}" if scale else ""
    return with_tz(
        'import "dict"\n'
        f"names = {names_dict(names)}\n"
        'from(bucket: "Homeassistant")\n'
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        f'  |> filter(fn: (r) => r._field == "value" and r.entity_id =~ /^({regex})$/)\n'
        "  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)\n"
        "  |> difference(nonNegative: true)\n"
        f"  |> map(fn: (r) => ({{_time: r._time, _value: r._value{sc}, _field: dict.get(dict: names, key: r.entity_id, default: r.entity_id)}}))\n"
        '  |> group(columns: ["_field"])'
    )


def q_state_timeline(names):
    return q_series(names, every="v.windowPeriod", fn="last")


def q_string_state(entity, label):
    return (
        'from(bucket: "Homeassistant")\n'
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        f'  |> filter(fn: (r) => r._field == "state" and r.entity_id == "{entity}")\n'
        f'  |> map(fn: (r) => ({{_time: r._time, _value: r._value, _field: "{label}"}}))\n'
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


def row(title):
    pid[0] += 1
    panels.append({"type": "row", "title": title, "id": pid[0], "collapsed": False,
                   "gridPos": {"x": 0, "y": y[0], "w": 24, "h": 1}, "panels": []})
    y[0] += 1


def stat(title, query, unit, decimals=1, color="blue", thresholds=None):
    return {
        "type": "stat", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "color": {"mode": "thresholds" if thresholds else "fixed", "fixedColor": color},
            "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": color, "value": None}]},
        }, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "value", "graphMode": "none", "textMode": "value", "justifyMode": "center"},
    }


def ts(title, query, unit, fill=10, stack=False, draw="line", overrides=None, interp="linear"):
    return {
        "type": "timeseries", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {
            "unit": unit, "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": draw, "lineWidth": 1, "fillOpacity": fill, "showPoints": "never",
                       "lineInterpolation": interp, "spanNulls": 3600000,
                       "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                       "barAlignment": 0},
        }, "overrides": overrides or []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "max", "lastNotNull"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def bars(title, query, unit, stack=True):
    p = ts(title, query, unit, fill=80, stack=stack, draw="bars")
    p["options"]["legend"]["calcs"] = ["sum", "mean"]
    p["interval"] = "1d"
    return p


def bargauge(title, query, unit):
    return {
        "type": "bargauge", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": 2, "min": 0,
                                     "color": {"mode": "continuous-GrYlRd"}}, "overrides": []},
        "options": {"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    }


def timeline(title, query, mappings=None):
    return {
        "type": "state-timeline", "title": title,
        "targets": [{"query": query}],
        "fieldConfig": {"defaults": {"color": {"mode": "thresholds"},
                                     "thresholds": {"mode": "absolute", "steps": [
                                         {"color": "transparent", "value": None}, {"color": "orange", "value": 0.5}]},
                                     "mappings": mappings or [], "custom": {"fillOpacity": 80, "lineWidth": 0}},
                        "overrides": []},
        "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8, "legend": {"showLegend": False}},
    }


# ------------------------------------------------------------------ Vue d'ensemble
row("Vue d'ensemble")
add(stat("Production PV", q_last("symo_15_0_3_m_1_ac_power"), "watt", 0, "yellow"), 4, 4, 0)
add(stat("Consommation maison", q_last("solarnet_power_load_consumed"), "watt", 0, "blue"), 4, 4, 4)
add(stat("Soutirage réseau", q_last("solarnet_power_grid_import"), "watt", 0, "red"), 4, 4, 8)
add(stat("Injection réseau", q_last("solarnet_power_grid_export"), "watt", 0, "green"), 4, 4, 12)
add(stat("Production PV aujourd'hui", q_last("symo_15_0_3_m_1_energy_day", "0.001"), "kwatth", 1, "yellow"), 4, 4, 16)
add(stat("Tarif actuel", q_last("groupee_vario"), "currencyCHF", 4, "purple"), 4, 4, 20)
y[0] += 4
add(stat("Autonomie", q_last("solarnet_autonomie_relative"), "percent", 0, "green",
         [{"color": "red", "value": None}, {"color": "orange", "value": 30}, {"color": "green", "value": 70}]), 4, 4, 0)
add(stat("Prévision PV aujourd'hui", q_last("energy_production_today"), "kwatth", 1, "yellow"), 4, 4, 4)
add(stat("Prévision restante", q_last("energy_production_today_remaining"), "kwatth", 1, "yellow"), 4, 4, 8)
add(stat("Prévision PV demain", q_last("energy_production_tomorrow"), "kwatth", 1, "yellow"), 4, 4, 12)
add(stat("Température extérieure", q_last("stiebel_eltron_isg_outdoor_temperature"), "celsius", 1, "text"), 4, 4, 16)
add(stat("Borne : puissance", q_last("go_echarger_411884_power_total"), "watt", 0, "blue"), 4, 4, 20)
y[0] += 4

# ------------------------------------------------------------------ Photovoltaïque
row("Photovoltaïque et réseau")
neg = [{"matcher": {"id": "byName", "options": "Injection"},
        "properties": [{"id": "custom.transform", "value": "negative-Y"}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
       {"matcher": {"id": "byName", "options": "Production PV"},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}}]},
       {"matcher": {"id": "byName", "options": "Soutirage"},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
       {"matcher": {"id": "byName", "options": "Consommation maison"},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "blue"}}, {"id": "custom.fillOpacity", "value": 0}]},
       {"matcher": {"id": "byName", "options": "Prévision PV"},
        "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}, {"id": "custom.fillOpacity", "value": 0},
                       {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]}]
add(ts("Flux d'énergie", q_series({
    "symo_15_0_3_m_1_ac_power": "Production PV",
    "solarnet_power_load_consumed": "Consommation maison",
    "solarnet_power_grid_import": "Soutirage",
    "solarnet_power_grid_export": "Injection",
    "power_production_now": "Prévision PV",
}), "watt", overrides=neg), 16, 9, 0)
add(ts("Strings PV (MPPT)", q_series({
    "ferme_symo_15_0_3_m_1_mppt_1_dc_power": "MPPT 1",
    "ferme_symo_15_0_3_m_1_mppt_2_dc_power": "MPPT 2",
}), "watt", stack=True), 8, 9, 16)
y[0] += 9
add(bars("Production PV par jour", q_daily_max({"symo_15_0_3_m_1_energy_day": "Production"}, "0.001"), "kwatth"), 12, 8, 0)
add(bars("Réseau par jour", q_daily_increase({
    "smart_meter_ts_65a_3_energie_reelle_consommee": "Soutirage",
    "smart_meter_ts_65a_3_energie_reelle_produite": "Injection",
}, "0.001"), "kwatth", stack=False), 12, 8, 12)
y[0] += 8

# ------------------------------------------------------------------ Prises
row("Prises connectées")
PLUGS = {
    "swiss_domotique_plug_8f8330": "Lave-linge",
    "swiss_domotique_plug_8f85f3": "Sèche-linge",
    "lave_vaiselle_haut": "Lave-vaisselle",
    "swiss_domotique_plug_574f67": "Télé box haut",
    "swiss_domotique_plug_5759d4": "PC / recharge meuble",
    "swiss_domotique_plug_576073": "Congélateur bahut",
    "congelateur_miele": "Congélateur Miele",
    "swiss_domotique_plug_f274a3": "Prise salon",
    "prise_nomade": "Prise nomade",
    "smart_plug_v2_57615c": "Prise vélo",
}
add(ts("Puissance des prises", q_series({f"{k}_power": v for k, v in PLUGS.items()}), "watt", fill=20, stack=True,
       interp="stepAfter"), 16, 9, 0)
add(bargauge("Énergie sur la période", q_increase({f"{k}_total_energy": v for k, v in PLUGS.items()}), "kwatth"), 8, 9, 16)
y[0] += 9
add(bars("Énergie des prises par jour", q_daily_increase({f"{k}_total_energy": v for k, v in PLUGS.items()}), "kwatth"), 24, 8, 0)
y[0] += 8

# ------------------------------------------------------------------ Chauffage
row("Chauffage")
add(ts("Températures", q_series({
    "stiebel_eltron_isg_outdoor_temperature": "Extérieur",
    "stiebel_eltron_isg_actual_temperature_hk_1": "Circuit 1",
    "stiebel_eltron_isg_target_temperature_hk_1": "Circuit 1 consigne",
    "stiebel_eltron_isg_actual_temperature_hk_2": "Circuit 2",
    "stiebel_eltron_isg_target_temperature_hk_2": "Circuit 2 consigne",
    "stiebel_eltron_isg_actual_temperature_water": "Eau chaude",
    "stiebel_eltron_isg_target_temperature_water": "Eau chaude consigne",
    "stiebel_eltron_isg_actual_temperature_buffer": "Ballon tampon",
    "stiebel_eltron_isg_flow_temperature_wp1": "Départ PAC",
    "stiebel_eltron_isg_return_temperature_wp1": "Retour PAC",
}), "celsius", fill=0, overrides=[
    {"matcher": {"id": "byRegexp", "options": ".*consigne"},
     "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]}]), 16, 9, 0)
add(ts("Puissance chauffage", q_series({
    "stiebel_eltron_wpmsystem_inverter_power_consumption": "PAC (onduleur)",
}, scale="1000.0") .replace("", ""), "watt"), 8, 9, 16)
# Askoheat + CE-Boiler dans le même panneau que la PAC
panels[-1]["targets"].append({"refId": "B", "datasource": DS, "query": q_series({
    "askoheat_power_w": "Askoheat",
    "ce_boiler_power": "CE-Boiler",
})})
y[0] += 9
add(timeline("États PAC", q_state_timeline({
    "stiebel_eltron_isg_compressor": "Compresseur",
    "stiebel_eltron_isg_is_heating": "Chauffage",
    "stiebel_eltron_isg_is_heating_boiler": "Eau chaude",
    "stiebel_eltron_isg_evaporator_defrost": "Dégivrage",
    "stiebel_eltron_isg_nhz_stages_running": "Appoint électrique",
    "stiebel_eltron_isg_power_off_evu": "Blocage EVU",
})), 24, 6, 0)
y[0] += 6
add(bars("Énergie PAC par jour", q_daily_max({
    "stiebel_eltron_isg_consumed_heating_today": "Consommé chauffage",
    "stiebel_eltron_isg_consumed_water_heating_today": "Consommé eau chaude",
    "stiebel_eltron_isg_produced_heating_today": "Produit chauffage",
    "stiebel_eltron_isg_produced_water_heating_today": "Produit eau chaude",
}), "kwatth", stack=False), 12, 8, 0)
add(bars("Askoheat et CE-Boiler par jour", q_daily_increase({
    "askoheat_energy": "Askoheat",
    "ce_boiler_energy": "CE-Boiler",
}), "kwatth"), 12, 8, 12)
y[0] += 8
add(ts("Circuit frigorifique", q_series({
    "stiebel_eltron_isg_high_pressure_wp1": "Haute pression",
    "stiebel_eltron_isg_low_pressure_wp1": "Basse pression",
}), "pressurebar", fill=0), 12, 7, 0)
add(ts("Débit et gaz chauds", q_series({
    "stiebel_eltron_isg_hot_gas_temperature_wp1": "Gaz chauds (°C)",
    "stiebel_eltron_isg_volume_stream_wp1": "Débit",
}), "none", fill=0), 12, 7, 12)
y[0] += 7

# ------------------------------------------------------------------ Borne
row("Borne de recharge")
add(ts("Puissance de charge", q_series({
    "go_echarger_411884_power_l1": "L1",
    "go_echarger_411884_power_l2": "L2",
    "go_echarger_411884_power_l3": "L3",
}), "watt", fill=40, stack=True, interp="stepAfter"), 16, 8, 0)
add(stat("Énergie session", q_last("go_echarger_411884_wh", "0.001"), "kwatth", 2, "blue"), 4, 4, 16)
add(stat("Total chargé", q_last("go_echarger_411884_total_energy_charged", "0.001"), "kwatth", 0, "blue"), 4, 4, 20)
add(stat("Courant autorisé", q_last("go_echarger_411884_allowed_charge_current"), "amp", 0, "text"), 4, 4, 16)
add(stat("Température borne", q_last("go_echarger_411884_temperature_0"), "celsius", 0, "text"), 4, 4, 20)
y[0] += 8
car = timeline("État véhicule", q_string_state("go_echarger_411884_car_state", "Véhicule"), mappings=[
    {"type": "value", "options": {
        "Idle": {"text": "Libre", "color": "transparent"},
        "WaitCar": {"text": "Attente véhicule", "color": "blue"},
        "Charging": {"text": "En charge", "color": "green"},
        "Complete": {"text": "Terminé", "color": "purple"},
        "Error": {"text": "Erreur", "color": "red"}}}])
car["fieldConfig"]["defaults"]["color"] = {"mode": "fixed", "fixedColor": "gray"}
add(car, 16, 4, 0)
add(bars("Énergie chargée par jour", q_daily_increase({"go_echarger_411884_total_energy_charged": "Borne"}, "0.001"), "kwatth"), 8, 8, 16)
y[0] += 4
add(ts("Courant de charge", q_series({
    "go_echarger_411884_current_l1": "L1",
    "go_echarger_411884_current_l2": "L2",
    "go_echarger_411884_current_l3": "L3",
}), "amp", fill=0, interp="stepAfter"), 16, 4, 0)
y[0] += 4

dash = {
    "uid": "energie-maison",
    "title": "Énergie maison",
    "tags": ["energie", "pv", "chauffage", "borne"],
    "timezone": "browser",
    "refresh": "1m",
    "time": {"from": "now-24h", "to": "now"},
    "schemaVersion": 39,
    "editable": True,
    "panels": panels,
}
json.dump({"dashboard": dash, "overwrite": True, "folderUid": "",
           "message": "Dashboard énergie maison (PV, prises, chauffage, borne)"},
          open(sys.argv[1], "w"), ensure_ascii=False, indent=2)
print(len(panels), "panneaux")
