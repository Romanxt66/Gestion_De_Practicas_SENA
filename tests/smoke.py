"""Smoke test: verifica que la app arranca y que todas las rutas GET responden
por rol sin errores 5xx. Uso:
  DATABASE_URL="sqlite:///$(pwd)/instance/flaskdb.sqlite" .venv/bin/python <ruta>/smoke.py
"""
import os, sys as _s; _s.path.insert(0, os.getcwd())
import sys
from app import create_app
from app.models.usuario import Usuario
from app.utils import get_user_role

app = create_app()
fallos = []

with app.app_context():
    por_rol = {}
    for u in Usuario.query.all():
        por_rol.setdefault(get_user_role(u), u.id_usuario)

rutas = sorted({str(r) for r in app.url_map.iter_rules()
                if 'GET' in r.methods and '<' not in str(r)
                and not str(r).startswith('/static')})

for rol, uid in por_rol.items():
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid); s['_fresh'] = True
    print(f"\n=== {rol} (usuario {uid}) ===")
    for ruta in rutas:
        code = c.get(ruta).status_code
        marca = ''
        if code >= 500:
            marca = '  <<< ERROR'
            fallos.append((rol, ruta, code))
        print(f"  {code} {ruta}{marca}")

print("\nRESULTADO:", "FALLOS -> %s" % fallos if fallos else "OK, sin errores 5xx")
sys.exit(1 if fallos else 0)
