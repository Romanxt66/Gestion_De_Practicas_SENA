# Pruebas

Suite con **pytest**. Cada ejecución crea su propia base SQLite temporal con
datos semilla (roles, un administrador, un instructor, dos aprendices y dos
fichas), así que no necesita `.env`, ni Postgres, ni `instance/flaskdb.sqlite`,
y no toca datos reales. El correo nunca sale: los transportes se sustituyen.

```bash
pip install -r requirements-test.txt
python -m pytest                    # todo
python -m pytest tests/test_auth.py # un archivo
python -m pytest -k evidencia       # por nombre
```

| Archivo | Cubre |
|---|---|
| `test_smoke.py` | Todas las rutas GET por rol sin errores 5xx; acceso por rol; caché y cabeceras |
| `test_utils.py` | `app/utils.py`: permisos, progreso, evidencias, fichas pendientes, archivos |
| `test_auth.py` | Login y perfiles, registro con confirmación de correo, CSRF, páginas legales |
| `test_admin.py` | Usuarios (alta, edición, bloqueo, borrado en cascada), roles, fichas, instructores, empresas, historial y exportaciones a Excel |
| `test_instructor.py` | Alcance por ficha y asignación directa, periodo de práctica, evaluación de evidencias, alertas |
| `test_aprendiz.py` | Subida de evidencias, mi ficha, datos personales, notificaciones, descarga protegida de archivos |
| `test_correo_google.py` | Servicio de correo (SMTP/Gmail), cifrado y flujo OAuth de Google, rutas `/cuenta` |
| `test_interfaz.py` | Armazón, tablas compactas, portal de acceso, panel móvil y sistema visual (CSS) |

`conftest.py` reúne los fixtures (`app`, `datos`, `c_admin`, `c_inst`, `c_ap`,
`anonimo`, `correos`, `avisos`) y los ayudantes (`crear_usuario`, `crear_curso`,
`token`, `texto`). La base es compartida por toda la sesión: las pruebas que
modifican o borran algo crean sus propios datos desechables en vez de tocar los
datos semilla.

## CI

`.github/workflows/tests.yml` ejecuta `pytest` en cada push a `main` y en cada
pull request, con Python 3.10 (la versión del `Dockerfile`).

## Scripts antiguos

`smoke.py` y `test_funcional.py` son los scripts previos a pytest. Siguen aquí
pero pytest los ignora: se ejecutan al importarse y exigen una copia local de
`instance/flaskdb.sqlite` con datos reales. Todo lo que comprobaban está ahora
en la suite de pytest.

```bash
RUN_DB_INIT=0 PYTHONPATH=. .venv/bin/python tests/smoke.py
PROY=$(pwd) .venv/bin/python tests/test_funcional.py
```
