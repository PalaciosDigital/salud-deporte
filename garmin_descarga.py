"""Descarga datos de Garmin Connect a ./datos (JSON).

Uso:
  ~/.venvs/salud/bin/python garmin_descarga.py login          # una sola vez (pide correo y clave)
  ~/.venvs/salud/bin/python garmin_descarga.py descargar 90   # últimos 90 días

Los tokens de sesión se guardan en ~/.garminconnect (fuera de iCloud, no se comparten).
La clave nunca se guarda.
"""
import json
import sys
import warnings
from datetime import date, timedelta
from getpass import getpass
from pathlib import Path

warnings.filterwarnings("ignore")
from garminconnect import Garmin  # noqa: E402

TOKENS = str(Path.home() / ".garminconnect")
DATOS = Path(__file__).resolve().parent / "datos"

# Métricas diarias: nombre -> función que recibe (cliente, "AAAA-MM-DD")
DIARIAS = {
    "resumen": lambda g, d: g.get_user_summary(d),          # pasos, calorías, estrés medio, FC reposo
    "sueno": lambda g, d: g.get_sleep_data(d),              # fases, puntaje, SpO2, respiración
    "hrv": lambda g, d: g.get_hrv_data(d),                  # VFC nocturna y estado
    "readiness": lambda g, d: g.get_training_readiness(d),  # preparación para entrenar
    "training_status": lambda g, d: g.get_training_status(d),  # carga aguda/crónica, estado
    "max_metrics": lambda g, d: g.get_max_metrics(d),       # VO2max
    "body_battery": lambda g, d: g.get_body_battery(d, d),
    "estres": lambda g, d: g.get_stress_data(d),
    "fc_reposo": lambda g, d: g.get_rhr_day(d),
}


def login():
    correo = input("Correo de Garmin: ").strip()
    clave = getpass("Clave de Garmin (no se muestra): ")
    g = Garmin(correo, clave, prompt_mfa=lambda: input("Código de verificación (MFA): ").strip())
    try:
        g.login(TOKENS)  # inicia sesión y guarda los tokens en TOKENS
    except Exception as e:
        sys.exit(f"\nNo se pudo iniciar sesión: {e}\nRevisa correo y clave (prueba entrar en connect.garmin.com).")
    print(f"\nListo. Sesión guardada en {TOKENS}")


def cliente():
    g = Garmin()
    try:
        g.login(TOKENS)
    except Exception as e:
        sys.exit(f"No hay sesión guardada o venció ({e}). Corre primero: garmin_descarga.py login")
    return g


def descargar(dias):
    g = cliente()
    hoy = date.today()
    inicio = hoy - timedelta(days=dias - 1)
    (DATOS / "diario").mkdir(parents=True, exist_ok=True)

    # Actividades: se suman a las ya guardadas (no se pierde el historial)
    archivo_acts = DATOS / "actividades.json"
    previas = json.loads(archivo_acts.read_text()) if archivo_acts.exists() else []
    nuevas = g.get_activities_by_date(inicio.isoformat(), hoy.isoformat())
    por_id = {a["activityId"]: a for a in previas}
    por_id.update({a["activityId"]: a for a in nuevas})
    acts = sorted(por_id.values(), key=lambda a: a["startTimeLocal"], reverse=True)
    archivo_acts.write_text(json.dumps(acts, ensure_ascii=False, indent=1))
    print(f"Actividades: {len(nuevas)} en el rango, {len(acts)} en total")

    refrescar_desde = (hoy - timedelta(days=2)).isoformat()
    for i in range(dias):
        d = (inicio + timedelta(days=i)).isoformat()
        archivo = DATOS / "diario" / f"{d}.json"
        if archivo.exists() and d < refrescar_desde:
            continue  # ya descargado; los últimos 3 días se refrescan siempre
        dia, errores = {}, []
        for nombre, f in DIARIAS.items():
            try:
                dia[nombre] = f(g, d)
            except Exception as e:  # una métrica que falle no frena el resto
                errores.append(f"{nombre}: {e.__class__.__name__}")
        archivo.write_text(json.dumps(dia, ensure_ascii=False))
        print(d, "ok" if not errores else "con fallos: " + ", ".join(errores))

    try:
        (DATOS / "predicciones_carrera.json").write_text(json.dumps(g.get_race_predictions(), ensure_ascii=False))
    except Exception:
        pass
    print(f"Datos en {DATOS}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "login":
        login()
    elif len(sys.argv) >= 2 and sys.argv[1] == "descargar":
        descargar(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    else:
        print(__doc__)
