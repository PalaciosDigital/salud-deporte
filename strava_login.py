"""Conecta tu cuenta de Strava (una sola vez, en la Mac).

  ~/.venvs/salud/bin/python strava_login.py

Pide el Client ID y el Client Secret de tu app de Strava, abre el navegador para que
autorices el acceso de solo lectura y guarda la sesión en ~/.garminconnect/strava.json
(fuera de iCloud y del repositorio). Luego `nube.py agregar` la sube cifrada.
"""
import json
import time
import urllib.parse
import urllib.request
import webbrowser
from getpass import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PUERTO = 8723
DESTINO = Path.home() / ".garminconnect" / "strava.json"
ALCANCE = "read,activity:read_all,profile:read_all"


def main():
    client_id = input("Client ID de tu app de Strava: ").strip()
    client_secret = getpass("Client Secret (no se muestra): ").strip()
    codigo = {}

    class Receptor(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            codigo["code"] = (q.get("code") or [None])[0]
            codigo["error"] = (q.get("error") or [None])[0]
            codigo["scope"] = (q.get("scope") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Listo, ya puedes cerrar esta pestaña y volver a la Terminal." if codigo["code"] else "No se autorizó el acceso."
            self.wfile.write(f"<p style='font:18px system-ui;padding:40px'>{msg}</p>".encode())

        def log_message(self, *a):
            pass

    url = "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "approval_prompt": "force",
        "redirect_uri": f"http://localhost:{PUERTO}/", "scope": ALCANCE,
    })
    print("\nSe abrirá Strava en el navegador. Pulsa «Autorizar».\nSi no se abre, copia este enlace:\n" + url)
    webbrowser.open(url)
    servidor = HTTPServer(("127.0.0.1", PUERTO), Receptor)
    while "code" not in codigo:
        servidor.handle_request()
    if not codigo.get("code"):
        raise SystemExit(f"Strava no dio acceso ({codigo.get('error')}).")
    if "activity:read_all" not in codigo["scope"]:
        print("Aviso: no marcaste ver actividades privadas; solo verá las públicas.")

    datos = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret,
                                    "code": codigo["code"], "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen("https://www.strava.com/oauth/token", data=datos, timeout=30) as r:
        t = json.load(r)
    sesion = {"client_id": client_id, "client_secret": client_secret, "refresh_token": t["refresh_token"],
              "access_token": t["access_token"], "expires_at": t["expires_at"],
              "atleta": (t.get("athlete") or {}).get("id"), "creado": int(time.time())}
    DESTINO.write_text(json.dumps(sesion))
    DESTINO.chmod(0o600)
    nombre = (t.get("athlete") or {}).get("firstname", "")
    print(f"\nListo{', ' + nombre if nombre else ''}. Strava conectado; sesión guardada en {DESTINO}")


if __name__ == "__main__":
    main()
