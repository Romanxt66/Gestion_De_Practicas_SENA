# Pruebas

No requieren pytest. Se ejecutan con el intérprete del entorno virtual desde la
raíz del proyecto.

```bash
# 1. Humo: todas las rutas GET, por cada rol, buscando errores 500
RUN_DB_INIT=0 PYTHONPATH=. .venv/bin/python tests/smoke.py

# 2. Funcional: flujos completos con CSRF, permisos, subida de archivos y CRUD.
#    Trabaja sobre una COPIA de instance/flaskdb.sqlite, no toca los datos reales.
PROY=$(pwd) .venv/bin/python tests/test_funcional.py
```

Correr ambas antes de dar por terminado cualquier cambio.
