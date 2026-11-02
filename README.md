# Salud y deporte

Tablero personal con datos de Garmin (Forerunner 965), actualizado cada hora por GitHub Actions.

- **Todo va cifrado.** El historial (`datos.enc`, rama `publicado`) usa AES-256-GCM con la llave del secreto `DATOS_KEY`. El tablero publicado en Pages lleva los datos cifrados con la contraseña del secreto `TABLERO_CLAVE` (PBKDF2-SHA256 + AES-256-GCM) y se descifra solo en el navegador.
- En este repositorio no hay datos de salud en claro, ni contraseñas, ni sesiones.

| Archivo | Qué hace |
|---|---|
| `nube.py` | Pipeline: descifra el historial, baja los últimos 4 días de Garmin, vuelve a cifrar y genera el tablero |
| `generar_tablero.py` | Resume los datos de Garmin y arma el HTML |
| `tablero_plantilla.html` | El tablero (gráficos, valoración, glosario) |
| `cifrado.py` | Cifrado de datos y del tablero |
| `garmin_descarga.py` | Descarga e inicio de sesión desde la Mac |
