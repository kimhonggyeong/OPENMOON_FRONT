from backend.app.config import get_settings
from backend.app.database import SessionLocal, init_db
from backend.app.services.price_service import import_price_table

if __name__ == "__main__":
    init_db()
    settings = get_settings()
    with SessionLocal() as session:
        result = import_price_table(session, settings.price_table_path)
    print(result)
