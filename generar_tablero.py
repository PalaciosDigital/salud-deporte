"""Convierte los datos de Garmin en el tablero.

Uso local:  ~/.venvs/salud/bin/python generar_tablero.py   (lee ./datos y escribe tablero.html)
En la nube lo usa nube.py: resumir_dia / resumir_actividad / renderizar.
"""
import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"


def g(o, *ruta):
    """Lee o[a][b][c] sin romperse si falta algo."""
    for k in ruta:
        if o is None:
            return None
        if isinstance(k, int):
            o = o[k] if isinstance(o, list) and len(o) > k else None
        else:
            o = o.get(k) if isinstance(o, dict) else None
    return o


def primero_de_mapa(o):
    """Garmin agrupa por id de reloj: {id: {...}} -> {...}."""
    return next(iter(o.values()), None) if isinstance(o, dict) and o else None


def r(x, n=1):
    return round(x, n) if isinstance(x, (int, float)) else None


def resumir_dia(fecha, d):
    s = g(d, "sueno", "dailySleepDTO") or {}
    hrv = g(d, "hrv", "hrvSummary") or {}
    rd = g(d, "readiness", 0) or {}
    ts = g(d, "training_status") or {}
    estado = primero_de_mapa(g(ts, "mostRecentTrainingStatus", "latestTrainingStatusData")) or {}
    carga = estado.get("acuteTrainingLoadDTO") or {}
    balance = primero_de_mapa(g(ts, "mostRecentTrainingLoadBalance", "metricsTrainingLoadBalanceDTOMap")) or {}
    res = g(d, "resumen") or {}

    bb = [v[1] for v in (g(d, "body_battery", 0, "bodyBatteryValuesArray") or []) if isinstance(v, list) and len(v) > 1 and v[1] is not None]
    bb += [v[2] for v in (g(d, "estres", "bodyBatteryValuesArray") or []) if isinstance(v, list) and len(v) > 2 and v[2] is not None]

    frase = estado.get("trainingStatusFeedbackPhrase") or ""
    return {
        "f": fecha,
        "sueno": g(s, "sleepScores", "overall", "value"),
        "sueno_h": r((s.get("sleepTimeSeconds") or 0) / 3600, 2) or None,
        "profundo": r((s.get("deepSleepSeconds") or 0) / 3600, 2),
        "rem": r((s.get("remSleepSeconds") or 0) / 3600, 2),
        "ligero": r((s.get("lightSleepSeconds") or 0) / 3600, 2),
        "despierto": r((s.get("awakeSleepSeconds") or 0) / 3600, 2),
        "spo2": s.get("averageSpO2Value"),
        "resp": s.get("averageRespirationValue"),
        "hrv": hrv.get("lastNightAvg"),
        "hrv_sem": hrv.get("weeklyAvg"),
        "hrv_lo": g(hrv, "baseline", "balancedLow"),
        "hrv_hi": g(hrv, "baseline", "balancedUpper"),
        "hrv_estado": hrv.get("status"),
        "fc_reposo": res.get("restingHeartRate") or g(d, "sueno", "restingHeartRate"),
        "bb_max": max(bb) if bb else None,
        "bb_min": min(bb) if bb else None,
        "bb_carga": g(d, "body_battery", 0, "charged"),
        "estres": res.get("averageStressLevel") if (res.get("averageStressLevel") or -1) >= 0 else None,
        "pasos": res.get("totalSteps"),
        "prep": rd.get("score"),
        "prep_nivel": rd.get("level"),
        "prep_frase": rd.get("feedbackShort"),
        "recuperacion_h": round(rd["recoveryTime"] / 60) if isinstance(rd.get("recoveryTime"), (int, float)) else None,  # Garmin lo da en minutos
        "carga_aguda": carga.get("dailyTrainingLoadAcute"),
        "carga_cronica": carga.get("dailyTrainingLoadChronic"),
        "carga_min": carga.get("minTrainingLoadChronic"),
        "carga_max": carga.get("maxTrainingLoadChronic"),
        "acwr": carga.get("dailyAcuteChronicWorkloadRatio"),
        "acwr_estado": carga.get("acwrStatus"),
        "estado": frase.rsplit("_", 1)[0] if frase else None,
        "vo2": g(ts, "mostRecentVO2Max", "generic", "vo2MaxPreciseValue"),
        "bal": {
            k: balance.get(k)
            for k in [
                "monthlyLoadAerobicLow", "monthlyLoadAerobicHigh", "monthlyLoadAnaerobic",
                "monthlyLoadAerobicLowTargetMin", "monthlyLoadAerobicLowTargetMax",
                "monthlyLoadAerobicHighTargetMin", "monthlyLoadAerobicHighTargetMax",
                "monthlyLoadAnaerobicTargetMin", "monthlyLoadAnaerobicTargetMax",
                "trainingBalanceFeedbackPhrase",
            ]
        } if balance else None,
    }


def resumir_actividad(a):
    tipo = g(a, "activityType", "typeKey") or "other"
    dist = a.get("distance") or 0
    dur = a.get("movingDuration") or a.get("duration") or 0
    return {
        "id": a.get("activityId"),
        "f": (a.get("startTimeLocal") or "")[:10],
        "hora": (a.get("startTimeLocal") or "")[11:16],
        "nombre": a.get("activityName"),
        "tipo": tipo,
        "km": r(dist / 1000, 2) if dist else None,
        "min": r(dur / 60, 1),
        "ritmo": r(dur / 60 / (dist / 1000), 2) if dist > 500 and "running" in tipo else None,  # min/km
        "fc": a.get("averageHR"),
        "fc_max": a.get("maxHR"),
        "carga": r(a.get("activityTrainingLoad"), 0),
        "te_aer": r(a.get("aerobicTrainingEffect"), 1),
        "te_ana": r(a.get("anaerobicTrainingEffect"), 1),
        "efecto": a.get("trainingEffectLabel"),
        "desnivel": r(a.get("elevationGain"), 0),
        "potencia": a.get("avgPower"),
        "np": r(a.get("normPower"), 0),
        "cadencia": r(a.get("averageRunningCadenceInStepsPerMinute"), 0),
        "zonas": [r((a.get(f"hrTimeInZone_{i}") or 0) / 60, 1) for i in range(1, 6)],
    }


def resumir_predicciones(pred):
    if isinstance(pred, list):
        pred = pred[0] if pred else None
    if not isinstance(pred, dict):
        return None
    return {k: pred.get(k) for k in ["time5K", "time10K", "timeHalfMarathon", "timeMarathon"]}


EXTRAS = ("umbrales", "plan", "marcas", "segmentos", "laboral")  # datos opcionales que también lee la plantilla


def paquete(dias: dict, actividades: dict, predicciones, **extra) -> dict:
    """Ordena el historial resumido en lo que lee la plantilla."""
    return {
        "generado": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "dias": [dias[k] for k in sorted(dias)],
        "actividades": sorted(actividades.values(), key=lambda a: (a["f"], a.get("hora") or ""), reverse=True),
        "predicciones": predicciones,
        **{k: v for k, v in extra.items() if k in EXTRAS and v},
    }


def resumir_umbrales(lt):
    """Umbral de lactato del reloj: FC (ppm), potencia (W) y ritmo de umbral."""
    sh = (lt or {}).get("speed_and_heart_rate") or {}
    pw = (lt or {}).get("power") or {}
    vel = sh.get("speed")  # Garmin la da en décimas de m/s
    return {"lthr": sh.get("heartRate"), "ftp": pw.get("functionalThresholdPower"),
            "ritmo_umbral": round(1000 / (vel * 10) / 60, 2) if vel else None,
            "fecha": (sh.get("calendarDate") or "")[:10]}


def laboral_para_entrenador(lab):
    """El entrenador ve cuánto trabajas y qué tipo de día es, no el contenido de tus tareas."""
    if not lab:
        return None
    por_dia = {}
    for t in lab.get("tareas") or []:
        d = por_dia.setdefault(t["f"], {"f": t["f"], "h": 0, "n": 0, "entregas": 0, "reuniones": 0})
        d["h"] += t.get("h") or 0
        d["n"] += 1
        d["entregas"] += (t.get("tipo") or "").lower() == "entrega"
        d["reuniones"] += (t.get("tipo") or "").lower() == "reunión"
    dias = [{"f": d["f"], "tipo": d["tipo"], "det": "Turno de redes" if "turno" in (d.get("det") or "").lower() else ""}
            for d in lab.get("dias") or []]
    semanas = [{k: s.get(k) for k in ("f", "habiles", "disp", "comp", "carga", "veredicto")} for s in lab.get("semanas") or []]
    return {"resumen_dias": sorted(por_dia.values(), key=lambda d: d["f"]), "dias": dias, "semanas": semanas}


def renderizar(datos: dict, contrasena=None, vista: str = "atleta") -> str:
    plantilla = (BASE / "tablero_plantilla.html").read_text()
    datos = {**datos, "vista": vista}
    if vista == "entrenador" and datos.get("laboral"):
        datos["laboral"] = laboral_para_entrenador(datos["laboral"])
    if contrasena:
        from cifrado import cifrar_para_web
        cif = cifrar_para_web(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), contrasena)
        return plantilla.replace("/*__CIFRADO__*/null", json.dumps(cif))
    return plantilla.replace("/*__DATOS__*/null", json.dumps(datos, ensure_ascii=False, separators=(",", ":")))


def historial_local():
    dias = {}
    for p in sorted((DATOS / "diario").glob("*.json")):
        try:
            dias[p.stem] = resumir_dia(p.stem, json.loads(p.read_text()))
        except Exception as e:
            print(f"Saltado {p.name}: {e}")
    acts_raw = json.loads((DATOS / "actividades.json").read_text()) if (DATOS / "actividades.json").exists() else []
    acts = {str(a["activityId"]): resumir_actividad(a) for a in acts_raw}
    pred_p = DATOS / "predicciones_carrera.json"
    pred = resumir_predicciones(json.loads(pred_p.read_text())) if pred_p.exists() else None
    return dias, acts, pred


def main():
    dias, acts, pred = historial_local()
    (BASE / "tablero.html").write_text(renderizar(paquete(dias, acts, pred)))
    print(f"tablero.html listo: {len(dias)} días, {len(acts)} actividades")


if __name__ == "__main__":
    main()
