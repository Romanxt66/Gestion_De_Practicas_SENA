import os

from app import create_app, db

app = create_app()


def inicializar_bd():
    """Ejecuta el seed inicial y, solo si no hay migraciones, crea las tablas.

    El esquema lo gestiona Alembic (`flask db upgrade`). Si además se llamara a
    `db.create_all()`, este crearía por su cuenta cualquier tabla nueva del
    modelo y la siguiente migración fallaría con "relation already exists".
    Por eso create_all() queda reservado a instalaciones sin carpeta
    migrations/, y el seed sigue corriendo siempre (salvo RUN_DB_INIT=0).
    """
    if os.getenv('RUN_DB_INIT', '1') != '1':
        print("RUN_DB_INIT=0 → se omite la inicialización.", flush=True)
        return

    from utils_seed import seed_data
    hay_migraciones = os.path.isdir(os.path.join(os.path.dirname(__file__), 'migrations'))

    with app.app_context():
        if hay_migraciones:
            print("Esquema gestionado por migraciones: no se ejecuta create_all(). "
                  "Aplica los cambios con 'flask db upgrade'.", flush=True)
        else:
            db.create_all()

        # El seed nunca debe impedir que el contenedor arranque: en una base
        # todavía sin migrar, las tablas no existen. Si fallara aquí, no habría
        # forma de entrar a la terminal para ejecutar 'flask db upgrade'.
        try:
            seed_data()
        except Exception as e:
            db.session.rollback()
            print(f"Seed omitido ({e.__class__.__name__}). "
                  "Si es una instalación nueva, ejecuta 'flask db upgrade' "
                  "y reinicia.", flush=True)


inicializar_bd()

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=int(os.getenv('PORT', 5001)))
