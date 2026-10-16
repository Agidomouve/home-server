"""Backfill InfluxDB avec l'historique HA (états bruts + statistiques horaires).

Usage : python3 -I import_ha_history.py <ha_config_dir> [--write]
Sans --write : simulation (comptages uniquement).
"""
import calendar, csv, fnmatch, io, json, re, sqlite3, subprocess, sys, time, urllib.request
from collections import defaultdict

HA = sys.argv[1]
WRITE = "--write" in sys.argv
ORG, BUCKET = "MaisonRussy", "Homeassistant"
URL = "http://localhost:8086"
NOW = time.time()

token = re.search(r"^influxdb_token:\s*(\S+)", open(f"{HA}/secrets.yaml").read(), re.M).group(1)

# --- Entités ciblées : mêmes globs/entities que le bloc influxdb de configuration.yaml
cfg = open(f"{HA}/configuration.yaml").read()
block = cfg.split("\ninfluxdb:")[1].split("\n\n\n")[0]
globs = re.findall(r"^\s+- ((?:binary_)?sensor\.\S+)", block.split("entities:")[0].split("entity_globs:")[1], re.M)
ents = re.findall(r"^\s+- ((?:binary_)?sensor\.\S+)", block.split("\n    entities:")[1], re.M)


def wanted(eid):
    return eid in ents or any(fnmatch.fnmatchcase(eid, g) for g in globs)


def flux(q):
    out = subprocess.run(["docker", "exec", "influxdb", "influx", "query", "--org", ORG, "--token", token, "--raw", q],
                         capture_output=True, text=True, check=True).stdout
    rows = [r for r in csv.reader(io.StringIO(out)) if r and not r[0].startswith("#")]
    if not rows:
        return []
    hdr = rows[0]
    return [dict(zip(hdr, r)) for r in rows[1:] if r != hdr]


db = sqlite3.connect(f"file:{HA}/home-assistant_v2.db?mode=ro", uri=True)
states_meta = {eid: mid for mid, eid in db.execute("select metadata_id, entity_id from states_meta") if wanted(eid)}
# HA récent : has_mean est remplacé par mean_type (0 = pas de moyenne)
stats_meta = {sid: (mid, unit, bool(has_mean or mean_type), has_sum) for mid, sid, unit, has_mean, mean_type, has_sum in
              db.execute("select id, statistic_id, unit_of_measurement, has_mean, mean_type, has_sum from statistics_meta") if wanted(sid)}
targets = sorted(set(states_meta) | set(stats_meta))
print(f"{len(targets)} entités ciblées ({len(globs)} globs, {len(ents)} entités explicites)")

# --- Premier point déjà présent dans InfluxDB + mesure (unité) utilisée par HA
first, meas = {}, {}
short = [t.split(".", 1)[1] for t in targets]
for i in range(0, len(short), 60):
    rx = "|".join(re.escape(s) for s in short[i:i + 60])
    for r in flux(f'from(bucket:"{BUCKET}") |> range(start: 2015-01-01T00:00:00Z) '
                  f'|> filter(fn:(r)=> r._field=="value" and r.entity_id =~ /^({rx})$/) '
                  f'|> group(columns:["entity_id"]) |> first() |> keep(columns:["entity_id","_time","_measurement"])'):
        t = r["_time"].replace("Z", "+00:00")
        first[r["entity_id"]] = calendar.timegm(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S"))
        meas[r["entity_id"]] = r["_measurement"]


def esc_m(s):
    return s.replace(",", r"\,").replace(" ", r"\ ")


def esc_t(s):
    return s.replace(",", r"\,").replace("=", r"\=").replace(" ", r"\ ")


def num(eid, s):
    if s in ("on", "off") and eid.startswith("binary_sensor."):
        return 1.0 if s == "on" else 0.0
    try:
        v = float(s)
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


lines, report, skipped = [], [], []
for eid in targets:
    dom, obj = eid.split(".", 1)
    cutoff = first.get(obj, NOW)
    m = meas.get(obj)
    st_unit = stats_meta.get(eid, (None, None))[1]
    if m is None:
        m = st_unit or "state"
    if eid.startswith("binary_sensor."):
        m = meas.get(obj, "state")
    key = f"{esc_m(m)},domain={dom},entity_id={esc_t(obj)}"
    n_states = n_stats = 0
    states_start = cutoff

    mid = states_meta.get(eid)
    if mid is not None:
        rows = db.execute("select state, last_updated_ts from states where metadata_id=? and last_updated_ts < ? "
                          "order by last_updated_ts", (mid, cutoff)).fetchall()
        if rows:
            states_start = rows[0][1]
        prev = None
        for s, ts in rows:
            v = num(eid, s)
            if v is None or v == prev:
                prev = None if v is None else prev
                continue
            prev = v
            lines.append(f"{key} value={v!r} {int(ts * 1000)}")
            n_states += 1
        # le premier état connu borne aussi la fenêtre des statistiques
        r0 = db.execute("select min(last_updated_ts) from states where metadata_id=?", (mid,)).fetchone()[0]
        if r0:
            states_start = min(states_start, r0)

    sm = stats_meta.get(eid)
    if sm:
        smid, unit, has_mean, has_sum = sm
        if unit and m.lower() != unit.lower() and m != "state" and not eid.startswith("binary_sensor."):
            skipped.append(f"{obj}: unité stats {unit} ≠ InfluxDB {m}")
        else:
            col = "mean" if has_mean else "state"
            for v, ts in db.execute(f"select {col}, start_ts from statistics where metadata_id=? and start_ts < ? "
                                    f"and {col} is not null order by start_ts",
                                    (smid, min(cutoff, states_start))):
                lines.append(f"{key} value={float(v)!r} {int(ts * 1000)}")
                n_stats += 1
    if n_states or n_stats:
        report.append((obj, m, n_states, n_stats, time.strftime("%Y-%m-%d", time.localtime(cutoff)) if obj in first else "-"))

for r in [r for r in report if r[4] != time.strftime("%Y-%m-%d")][:40]:
    print(f"  {r[0][:55]:55} [{r[1]}] états={r[2]} stats={r[3]} 1er point Influx={r[4]}")
print(f"... {len(report)} entités avec données à importer")
print(f"TOTAL : {sum(r[2] for r in report)} états bruts + {sum(r[3] for r in report)} points horaires = {len(lines)} lignes")
for s in skipped:
    print("  IGNORÉ", s)

if WRITE:
    hdr = {"Authorization": f"Token {token}", "Content-Type": "text/plain; charset=utf-8"}
    url = f"{URL}/api/v2/write?org={ORG}&bucket={BUCKET}&precision=ms"
    for i in range(0, len(lines), 5000):
        req = urllib.request.Request(url, "\n".join(lines[i:i + 5000]).encode(), hdr)
        urllib.request.urlopen(req).read()
        if i // 5000 % 50 == 0:
            print(f"  écrit {i + 5000}/{len(lines)}", flush=True)
    print("ÉCRITURE TERMINÉE")
