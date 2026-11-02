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
