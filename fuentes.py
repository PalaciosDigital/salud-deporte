"""Fuentes extra del tablero: Strava (mejores marcas y segmentos) y TrainingPeaks (plan).

Las credenciales viven solo dentro de datos.enc (cifrado):
  h["strava_sesion"] = {client_id, client_secret, refresh_token, access_token, expires_at}
  h["tp_ical"]       = enlace privado del calendario de TrainingPeaks
Lo que llega al tablero (también cifrado con tu contraseña) son solo resúmenes:
  h["marcas"], h["segmentos"], h["plan"].
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

UA = {"User-Agent": "tablero-salud-deporte"}

# ---------------------------------------------------------------- Strava
STRAVA = "https://www.strava.com/api/v3"
CARRERA = {"Run", "TrailRun", "VirtualRun"}
DETALLES_POR_CORRIDA = 40          # límite de Strava: 100 lecturas cada 15 min, 1000 al día
DISTANCIAS = ["400m", "1/2 mile", "1k", "1 mile", "2 mile", "5k", "10k", "15k", "10 mile", "20k", "Half-Marathon", "30k", "Marathon"]


def _json(url, datos=None, token=None):
    cab = dict(UA)
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(datos).encode() if datos else None, headers=cab)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _token_strava(s):
    if s.get("access_token") and s.get("expires_at", 0) > time.time() + 300:
        return s["access_token"]
    t = _json("https://www.strava.com/oauth/token", {
        "client_id": s["client_id"], "client_secret": s["client_secret"],
        "grant_type": "refresh_token", "refresh_token": s["refresh_token"]})
    s.update(access_token=t["access_token"], refresh_token=t["refresh_token"], expires_at=t["expires_at"])
    return s["access_token"]


def actualizar_strava(h):
    s = h.get("strava_sesion")
    if not s:
        return
    tok = _token_strava(s)
    st = h.setdefault("strava", {"vistas": {}, "pendientes": [], "segcat": {}, "ultimo_inicio": 0})

    # 1) Lista de actividades nuevas (la primera vez recorre todo el historial)
    pagina, nuevas = 1, 0
    while pagina <= 10:
        lote = _json(f"{STRAVA}/athlete/activities?" + urllib.parse.urlencode(
            {"after": st["ultimo_inicio"], "per_page": 100, "page": pagina}), token=tok)
        if not lote:
            break
        for a in lote:
            inicio = int(datetime.fromisoformat(a["start_date"].replace("Z", "+00:00")).timestamp())
            st["ultimo_inicio"] = max(st["ultimo_inicio"], inicio)
            if (a.get("sport_type") or a.get("type")) in CARRERA and str(a["id"]) not in st["vistas"] \
                    and str(a["id"]) not in st["pendientes"]:
                st["pendientes"].append(str(a["id"]))
                nuevas += 1
        pagina += 1

    # 2) Detalle (mejores esfuerzos y segmentos) de algunas por corrida; el resto en la siguiente
    hechas = 0
    while st["pendientes"] and hechas < DETALLES_POR_CORRIDA:
        aid = st["pendientes"].pop()  # las más recientes primero
        try:
            a = _json(f"{STRAVA}/activities/{aid}", token=tok)
        except urllib.error.HTTPError as e:
            if e.code == 429:  # límite de Strava: se retoma la próxima vez
                st["pendientes"].append(aid)
                break
            continue
        hechas += 1
        st["vistas"][aid] = {
            "f": (a.get("start_date_local") or "")[:10],
            "n": a.get("name"),
            "be": {b["name"]: b["elapsed_time"] for b in a.get("best_efforts") or []},
            "seg": [[str(e["segment"]["id"]), e["elapsed_time"], e.get("pr_rank")] for e in a.get("segment_efforts") or []
                    if not (e.get("segment") or {}).get("private")],
        }
        for e in a.get("segment_efforts") or []:
            sg = e.get("segment") or {}
            st["segcat"][str(sg.get("id"))] = {"n": sg.get("name"), "d": round(sg.get("distance") or 0),
                                               "g": sg.get("average_grade"), "c": sg.get("city")}
    print(f"Strava: {nuevas} carreras nuevas, {hechas} detalladas, {len(st['pendientes'])} pendientes")

    # 3) Resúmenes para el tablero
    marcas = {}
    for aid, v in st["vistas"].items():
        for nombre, t in v["be"].items():
            marcas.setdefault(nombre, []).append([v["f"], t, aid])
    h["marcas"] = {k: sorted(marcas[k]) for k in DISTANCIAS if k in marcas}

    intentos = {}
    for aid, v in st["vistas"].items():
        for sid, t, _ in v["seg"]:
            intentos.setdefault(sid, []).append([v["f"], t, aid])
    top = sorted(intentos.items(), key=lambda kv: len(kv[1]), reverse=True)[:20]
    h["segmentos"] = [{"id": sid, **st["segcat"].get(sid, {}), "intentos": sorted(lst)} for sid, lst in top]


# ---------------------------------------------------------------- TrainingPeaks (iCal)
def _desdoblar(texto):
    return re.sub(r"\r?\n[ \t]", "", texto)


def _limpiar(v):
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _minutos(texto):
    m = re.search(r"(?i)(?:duraci[oó]n|duration|time|tiempo)[^0-9]{0,20}(\d{1,2}):(\d{2})(?::(\d{2}))?", texto)
    if m:
        h_, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return round(h_ * 60 + mi + s / 60) if m.group(3) is not None else h_ * 60 + mi
    m = re.search(r"(?i)(\d+(?:[.,]\d+)?)\s*(h|hr|hrs|hora|horas)\b", texto)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 60)
    m = re.search(r"(?i)(\d{2,3})\s*(min|minutos|mins)\b", texto)
    return int(m.group(1)) if m else None


def _km(texto):
    m = re.search(r"(?i)(\d+(?:[.,]\d+)?)\s*(km|kilómetros|kilometros)\b", texto)
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.search(r"(?i)(\d+(?:[.,]\d+)?)\s*(mi|miles|millas)\b", texto)
    return round(float(m.group(1).replace(",", ".")) * 1.609, 2) if m else None


def _tss(texto):
    m = re.search(r"(?i)\bTSS\b[^0-9]{0,5}(\d+(?:[.,]\d+)?)", texto)
    return round(float(m.group(1).replace(",", "."))) if m else None


def _tipo(texto):
    t = texto.lower()
    for clave, nombre in [("swim", "Natación"), ("nata", "Natación"), ("bike", "Ciclismo"), ("cicl", "Ciclismo"),
                          ("strength", "Fuerza"), ("fuerza", "Fuerza"), ("gym", "Fuerza"), ("walk", "Caminata"),
                          ("descanso", "Descanso"), ("rest", "Descanso"), ("day off", "Descanso"),
                          ("run", "Carrera"), ("corr", "Carrera"), ("trote", "Carrera"), ("rodaje", "Carrera"),
                          ("series", "Carrera"), ("fartlek", "Carrera"), ("tempo", "Carrera")]:
        if clave in t:
            return nombre
    return "Otro"


def actualizar_plan(h):
    url = h.get("tp_ical")
    if not url:
        return
    url = url.strip().replace("webcal://", "https://")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        ics = _desdoblar(r.read().decode("utf-8", "replace"))
    desde, hasta = (date.today() - timedelta(days=400)).isoformat(), (date.today() + timedelta(days=60)).isoformat()
    plan = {}
    for bloque in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics, re.S):
        campos = {}
        for linea in bloque.strip().splitlines():
            if ":" in linea:
                k, v = linea.split(":", 1)
                campos[k.split(";")[0].upper()] = _limpiar(v)
        ini = campos.get("DTSTART", "")
        if not re.match(r"\d{8}", ini):
            continue
        f = f"{ini[:4]}-{ini[4:6]}-{ini[6:8]}"
        if not (desde <= f <= hasta):
            continue
        titulo, desc = campos.get("SUMMARY", ""), campos.get("DESCRIPTION", "")
        texto = f"{titulo}\n{desc}"
        uid = campos.get("UID") or f"{f}-{titulo}"
        plan[uid] = {"f": f, "t": titulo[:120], "d": desc[:600], "min": _minutos(texto), "km": _km(texto),
                     "tss": _tss(texto), "tipo": _tipo(texto)}
    h["plan"] = sorted(plan.values(), key=lambda p: (p["f"], p["t"]))
    print(f"TrainingPeaks: {len(h['plan'])} sesiones en el calendario")


# ---------------------------------------------------------------- Plan desde el calendario de Garmin
# TrainingPeaks envía a Garmin Connect los entrenamientos que programa tu entrenador;
# los leemos del calendario de Garmin con la misma sesión que ya usa el tablero.
DEPORTE = {"running": "Carrera", "trail_running": "Carrera", "treadmill_running": "Carrera", "track_running": "Carrera",
           "strength_training": "Fuerza", "cycling": "Ciclismo", "road_biking": "Ciclismo", "indoor_cycling": "Ciclismo",
           "swimming": "Natación", "lap_swimming": "Natación", "walking": "Caminata", "hiking": "Caminata",
           "cardio_training": "Otro", "yoga": "Otro", "other": "Otro"}
TIPO_PASO = {"warmup": "Calentamiento", "cooldown": "Vuelta a la calma", "interval": "Trabajo", "recovery": "Recuperación",
             "rest": "Descanso", "active": "Trabajo", "other": "Paso", "main": "Trabajo"}


def _ritmo_txt(v):
    if not v:
        return ""
    s = 1000 / v
    return f"{int(s // 60)}:{int(round(s % 60)):02d}"


def _paso(p):
    """Describe un paso de entrenamiento estructurado en una línea."""
    if p.get("type") == "RepeatGroupDTO" or p.get("numberOfIterations"):
        dentro = " + ".join(_paso(x) for x in p.get("workoutSteps") or [])
        return f"{p.get('numberOfIterations') or '?'}× ({dentro})"
    nombre = TIPO_PASO.get(((p.get("stepType") or {}).get("stepTypeKey") or "").lower(), "Paso")
    cond = ((p.get("endCondition") or {}).get("conditionTypeKey") or "").lower()
    val = p.get("endConditionValue")
    dur = ""
    if cond == "time" and val:
        dur = f"{int(val // 60)} min" + (f" {int(val % 60)} s" if val % 60 else "")
    elif cond == "distance" and val:
        dur = f"{val / 1000:g} km" if val >= 1000 else f"{int(val)} m"
    elif cond == "lap.button":
        dur = "hasta pulsar vuelta"
    obj = ""
    tt = ((p.get("targetType") or {}).get("workoutTargetTypeKey") or "").lower()
    a, b = p.get("targetValueOne"), p.get("targetValueTwo")
    if tt == "pace.zone" and a and b:
        obj = f" a {_ritmo_txt(max(a, b))}–{_ritmo_txt(min(a, b))} /km"
    elif tt == "heart.rate.zone" and a and b:
        obj = f" a {int(min(a, b))}–{int(max(a, b))} ppm"
    elif tt == "heart.rate.zone" and p.get("zoneNumber"):
        obj = f" en zona {p['zoneNumber']} de pulso"
    elif tt == "power.zone" and a and b:
        obj = f" a {int(min(a, b))}–{int(max(a, b))} W"
    return f"{nombre} {dur}{obj}".strip()


def _resumen_workout(w):
    pasos = []
    for seg in w.get("workoutSegments") or []:
        pasos += [_paso(p) for p in seg.get("workoutSteps") or []]
    desc = (w.get("description") or "").strip()
    return "\n".join([desc] + pasos if desc else pasos)[:600]


def actualizar_plan_garmin(g, h):
    hoy = date.today()
    meses = sorted({((hoy.year * 12 + hoy.month - 1 + d) // 12, (hoy.month - 1 + d) % 12 + 1) for d in range(-4, 2)})
    items, claves = [], set()
    for y, m in meses:
        r = g.get_scheduled_workouts(y, m) or {}
        lote = r.get("calendarItems") if isinstance(r, dict) else r
        for it in lote or []:
            claves.update(it.keys())
            if (it.get("itemType") or "").lower() == "workout":
                items.append(it)
    cache = h.setdefault("plan_cache", {})  # descripción de entrenamientos ya leídos
    plan, vistos, proveedores = [], set(), {}
    for it in items:
        f = (it.get("date") or "")[:10]
        if not f:
            continue
        wid = str(it.get("workoutId") or it.get("id") or "")
        info = cache.get(wid)
        if info is None and wid:
            try:
                w = g.get_workout_by_id(wid)
                info = cache[wid] = {"d": _resumen_workout(w), "seg": w.get("estimatedDurationInSecs"),
                                     "dist": w.get("estimatedDistanceInMeters"),
                                     "prov": str(w.get("workoutProvider") or w.get("workoutSourceId") or w.get("author", {}).get("displayName") and "autor" or "")[:40]}
            except Exception:
                info = {}
        info = info or {}
        clave = (f, wid)
        if clave in vistos:
            continue
        vistos.add(clave)
        texto = info.get("d", "")
        proveedores[info.get("prov") or "desconocido"] = proveedores.get(info.get("prov") or "desconocido", 0) + 1
        seg = it.get("duration") or info.get("seg")
        dist = it.get("distance") or info.get("dist")
        plan.append({"f": f, "t": (it.get("title") or "")[:120], "d": texto or "",
                     "min": round(seg / 60) if isinstance(seg, (int, float)) and seg > 0 else None,
                     "km": round(dist / 1000, 1) if isinstance(dist, (int, float)) and dist > 0 else None,
                     "tss": None, "tipo": DEPORTE.get((it.get("sportTypeKey") or "").lower(), "Otro")})
    # Solo conteos en el registro: el registro de GitHub Actions es público
    futuros = sum(1 for p in plan if p["f"] >= hoy.isoformat())
    print(f"Plan (calendario de Garmin): {len(plan)} entrenamientos ({futuros} desde hoy). Origen: {proveedores}")
    if not h.get("tp_ical"):
        h["plan"] = sorted(plan, key=lambda p: (p["f"], p["t"]))


# ---------------------------------------------------------------- Planificación laboral (Google Sheets)
# La hoja está compartida por enlace: se lee como CSV sin credenciales. El ID vive solo en datos.enc.
import csv
import io

HOJAS = {"tareas": 578440063, "calendario": 777001, "capacidad": 1517959498}
MESES_ES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                        "septiembre", "octubre", "noviembre", "diciembre"], 1)}


def _fecha_es(t):
    """'octubre 29, 2026' / '2026-10-29' / '29/10/2026' -> '2026-10-29'."""
    t = (t or "").strip().lower()
    m = re.match(r"([a-záéíóú]+)\s+(\d{1,2}),\s*(\d{4})", t)
    if m and m.group(1) in MESES_ES:
        return f"{m.group(3)}-{MESES_ES[m.group(1)]:02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def _num(t):
    try:
        return float(str(t).replace("%", "").replace(",", ".").strip())
    except ValueError:
        return None


def _csv(hoja_id, gid):
    url = f"https://docs.google.com/spreadsheets/d/{hoja_id}/export?format=csv&gid={gid}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return list(csv.reader(io.StringIO(r.read().decode("utf-8", "replace"))))


def _tabla(filas, primera_col):
    """Devuelve (encabezado, filas) a partir de la fila cuya primera celda es `primera_col`."""
    for i, f in enumerate(filas):
        if f and f[0].strip().lower() == primera_col:
            return [c.strip().lower() for c in f], filas[i + 1:]
    return [], []


def actualizar_laboral(h):
    hoja = h.get("hoja_laboral")
    if not hoja:
        return
    desde, hasta = (date.today() - timedelta(days=120)).isoformat(), (date.today() + timedelta(days=90)).isoformat()

    cab, filas = _tabla(_csv(hoja, HOJAS["tareas"]), "fecha")
    col = {k: cab.index(k) for k in ("fecha", "proyecto", "tarea", "tipo", "horas", "estado") if k in cab}
    tareas = []
    for f in filas:
        fe = _fecha_es(f[col["fecha"]]) if "fecha" in col and len(f) > col["fecha"] else None
        if not fe or not (desde <= fe <= hasta):
            continue
        g_ = lambda k: f[col[k]].strip() if k in col and len(f) > col[k] else ""
        if not g_("tarea"):
            continue
        tareas.append({"f": fe, "proy": g_("proyecto")[:80], "tarea": g_("tarea")[:140], "tipo": g_("tipo"),
                       "h": _num(g_("horas")), "estado": g_("estado")})

    # Días especiales: bloque "Fecha / Tipo / Detalle" a la derecha del calendario
    dias = []
    for f in _csv(hoja, HOJAS["calendario"]):
        for j in range(len(f) - 1):
            fe = _fecha_es(f[j])
            if fe and f[j + 1].strip() in ("Libre", "Feriado", "Hito", "") and len(f[j]) > 10 and desde <= fe <= hasta:
                tipo = f[j + 1].strip() or "Nota"
                dias.append({"f": fe, "tipo": tipo, "det": (f[j + 2].strip() if len(f) > j + 2 else "")[:80]})
                break

    cab, filas = _tabla(_csv(hoja, HOJAS["capacidad"]), "semana (lunes)")
    semanas = []
    for f in filas:
        fe = _fecha_es(f[0]) if f else None
        if not fe:
            continue
        v = lambda i: f[i].strip() if len(f) > i else ""
        semanas.append({"f": fe, "habiles": _num(v(1)), "disp": _num(v(2)), "comp": _num(v(3)),
                        "carga": _num(v(4)), "veredicto": v(5), "resumen": v(6)[:300]})

    h["laboral"] = {"tareas": tareas, "dias": dias, "semanas": semanas}
    print(f"Planificación laboral: {len(tareas)} tareas, {len(dias)} días especiales, {len(semanas)} semanas")
