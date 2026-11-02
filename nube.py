"""Pipeline en la nube (GitHub Actions): Garmin -> historial cifrado -> tablero cifrado.

  python nube.py actualizar <datos.enc> <carpeta_salida>   # lo corre GitHub Actions
  python nube.py sembrar <carpeta_salida>                   # una vez, en la Mac: sube el historial local

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
from generar_tablero import paquete, renderizar, resumir_actividad, resumir_dia, resumir_predicciones  # noqa: E402

DIAS_A_REFRESCAR = 4


def publicar(h: dict, salida: Path, llave: bytes, clave: str):
    """salida/datos.enc = historial (rama publicado); salida/web = lo que se publica en Pages."""
    web = salida / "web"
    web.mkdir(parents=True, exist_ok=True)
    (salida / "datos.enc").write_bytes(cifrar_objeto(h, llave))
    (web / "index.html").write_text(renderizar(paquete(h["dias"], h["actividades"], h.get("predicciones")), clave))
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


if __name__ == "__main__":
    if sys.argv[1:2] == ["actualizar"]:
        actualizar(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1:2] == ["sembrar"]:
        sembrar(Path(sys.argv[2]))
    else:
        print(__doc__)
