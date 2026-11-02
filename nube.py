"""Pipeline en la nube (GitHub Actions): Garmin -> historial cifrado -> tablero cifrado.

  python nube.py actualizar <datos.enc> <carpeta_salida>   # lo corre GitHub Actions
  python nube.py sembrar <carpeta_salida>                   # una vez, en la Mac: sube el historial local
  python nube.py agregar <datos.enc>                        # en la Mac: suma Strava / TrainingPeaks / potencia

Variables: DATOS_KEY (llave de 32 bytes en base64) y TABLERO_CLAVE (contraseña del tablero).
Nada se escribe sin cifrar: datos.enc lleva el historial resumido y la sesión de Garmin;
index.html lleva los datos cifrados con la contraseña.
"""
import base64
import json
import os
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
from cifrado import cifrar_objeto, descifrar_objeto, llave_desde_texto  # noqa: E402
from generar_tablero import paquete, renderizar, resumir_actividad, resumir_dia, resumir_predicciones, resumir_umbrales, EXTRAS  # noqa: E402

DIAS_A_REFRESCAR = 4


def publicar(h: dict, salida: Path, llave: bytes, clave: str):
    """salida/datos.enc = historial (rama publicado); salida/web = lo que se publica en Pages."""
    web = salida / "web"
    web.mkdir(parents=True, exist_ok=True)
    (salida / "datos.enc").write_bytes(cifrar_objeto(h, llave))
    datos = paquete(h["dias"], h["actividades"], h.get("predicciones"), **{k: h.get(k) for k in EXTRAS})
    (web / "index.html").write_text(renderizar(datos, clave, "atleta"))
    clave_ent = os.environ.get("ENTRENADOR_CLAVE")
    if clave_ent:  # vista del entrenador, con su propia contraseña
        (web / "entrenador").mkdir(exist_ok=True)
        (web / "entrenador" / "index.html").write_text(renderizar(datos, clave_ent, "entrenador"))
    (web / ".nojekyll").write_text("")
    (web / "robots.txt").write_text("User-agent: *\nDisallow: /\n")


def actualizar(entrada: Path, salida: Path):
    from garminconnect import Garmin
    from garmin_descarga import DIARIAS

    llave = llave_desde_texto(os.environ["DATOS_KEY"])
    clave = os.environ["TABLERO_CLAVE"]
    h = descifrar_objeto(entrada.read_bytes(), llave)

    g = Garmin()
    g.login(h["tokens"])  # sesión guardada (JSON); se renueva sola

    hoy = date.today()
    inicio = hoy - timedelta(days=DIAS_A_REFRESCAR - 1)
    nuevas = g.get_activities_by_date(inicio.isoformat(), hoy.isoformat())
    for a in nuevas:
        h["actividades"][str(a["activityId"])] = resumir_actividad(a)
    print(f"Actividades nuevas o actualizadas: {len(nuevas)} (total {len(h['actividades'])})")

    for i in range(DIAS_A_REFRESCAR):
        d = (inicio + timedelta(days=i)).isoformat()
        crudo, fallos = {}, []
        for nombre, f in DIARIAS.items():
            try:
                crudo[nombre] = f(g, d)
            except Exception as e:
                fallos.append(f"{nombre}: {e.__class__.__name__}")
        h["dias"][d] = resumir_dia(d, crudo)
        print(d, "ok" if not fallos else "con fallos: " + ", ".join(fallos))

    try:
        h["predicciones"] = resumir_predicciones(g.get_race_predictions()) or h.get("predicciones")
    except Exception:
        pass
    try:
        h["umbrales"] = resumir_umbrales(g.get_lactate_threshold(latest=True)) or h.get("umbrales")
    except Exception as e:
        print("Umbral de lactato no disponible:", e.__class__.__name__)

    # Fuentes extra: si fallan, el tablero se publica igual con lo de Garmin
    from fuentes import actualizar_laboral, actualizar_plan, actualizar_plan_garmin, actualizar_strava
    for nombre, fn in (("Plan (Garmin)", lambda h_: actualizar_plan_garmin(g, h_)), ("Planificación laboral", actualizar_laboral),
                       ("Strava", actualizar_strava), ("TrainingPeaks", actualizar_plan)):
        try:
            fn(h)
        except Exception as e:
            print(f"{nombre} no disponible esta vez: {e.__class__.__name__}: {str(e)[:120]}")

    h["tokens"] = g.client.dumps()  # guarda la sesión renovada para la próxima vez
    h["actualizado"] = datetime.now().isoformat(timespec="minutes")
    publicar(h, salida, llave, clave)
    print(f"Publicado: {len(h['dias'])} días, {len(h['actividades'])} actividades")


def sembrar(salida: Path):
    from generar_tablero import historial_local

    archivo_llave = Path.home() / ".garminconnect" / "datos_key"
    if not archivo_llave.exists():
        archivo_llave.write_text(base64.b64encode(os.urandom(32)).decode())
        archivo_llave.chmod(0o600)
    llave = llave_desde_texto(archivo_llave.read_text())
    dias, acts, pred = historial_local()
    tokens = (Path.home() / ".garminconnect" / "garmin_tokens.json").read_text()
    h = {"dias": dias, "actividades": acts, "predicciones": pred, "tokens": tokens,
         "actualizado": datetime.now().isoformat(timespec="minutes")}
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "datos.enc").write_bytes(cifrar_objeto(h, llave))
    (salida / ".nojekyll").write_text("")
    print(f"Sembrado: {len(dias)} días, {len(acts)} actividades -> {salida/'datos.enc'}")


def agregar(archivo: Path):
    """En la Mac: abre datos.enc y le suma lo que haya en ~/.garminconnect (Strava, TrainingPeaks)
    más la potencia normalizada del historial local. No toca la sesión de Garmin de la nube."""
    carpeta = Path.home() / ".garminconnect"
    llave = llave_desde_texto((carpeta / "datos_key").read_text())
    h = descifrar_objeto(archivo.read_bytes(), llave)
    cambios = []
    s = carpeta / "strava.json"
    if s.exists():
        h["strava_sesion"] = json.loads(s.read_text())
        cambios.append("Strava")
    hl = carpeta / "hoja_laboral"
    if hl.exists() and hl.read_text().strip():
        h["hoja_laboral"] = hl.read_text().strip()
        cambios.append("hoja laboral")
    t = carpeta / "tp_ical_url"
    if t.exists() and t.read_text().strip().startswith(("http", "webcal")):
        h["tp_ical"] = t.read_text().strip()
        cambios.append("TrainingPeaks")
    local = Path(os.environ.get("SALUD_LOCAL", "")) / "datos" / "actividades.json"
    if local.exists():
        n = 0
        for a in json.loads(local.read_text()):
            v = h["actividades"].get(str(a["activityId"]))
            if v is not None and a.get("normPower") and not v.get("np"):
                v["np"] = round(a["normPower"])
                n += 1
        cambios.append(f"potencia normalizada en {n} actividades")
    archivo.write_bytes(cifrar_objeto(h, llave))
    print("Agregado:", ", ".join(cambios) or "nada nuevo")


if __name__ == "__main__":
    if sys.argv[1:2] == ["actualizar"]:
        actualizar(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1:2] == ["agregar"]:
        agregar(Path(sys.argv[2]))
    elif sys.argv[1:2] == ["sembrar"]:
        sembrar(Path(sys.argv[2]))
    else:
        print(__doc__)
