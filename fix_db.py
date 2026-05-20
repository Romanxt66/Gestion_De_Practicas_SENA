from app import create_app, db
from app.models.historial_cambios import HistorialCambios

app = create_app()
with app.app_context():
    historial = HistorialCambios.query.all()
    count = 0
    for h in historial:
        if h.descripcion and 'Ã' in h.descripcion:
            try:
                # Try to decode from latin1 to utf-8
                fixed = h.descripcion.encode('latin1').decode('utf-8')
                h.descripcion = fixed
                count += 1
            except Exception as e:
                print(f"Error on {h.id_historial}: {e}")
    db.session.commit()
    print(f"Fixed {count} records in database.")
