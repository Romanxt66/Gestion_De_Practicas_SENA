import os

from app import create_app, db

app = create_app()


def inicializar_bd():
    """Crea las tablas que falten y ejecuta el seed inicial.

    Se puede desactivar con RUN_DB_INIT=0. Recomendado desactivarlo cuando se
    corre con varios workers (para que no compitan entre sí) y gestionar el
    esquema con migraciones:  flask db upgrade
    """
    if os.getenv('RUN_DB_INIT', '1') != '1':
        print("RUN_DB_INIT=0 → se omite create_all()/seed.", flush=True)
        return
    from utils_seed import seed_data
    with app.app_context():
        db.create_all()
        seed_data()


inicializar_bd()

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=int(os.getenv('PORT', 5001)))
