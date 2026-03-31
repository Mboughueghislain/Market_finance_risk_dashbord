# db/config.py — paramètres de connexion à la base de données
#
# Priorité de chargement :
#   1. Variables d'environnement système (Docker, CI/CD, Streamlit Cloud)
#   2. Fichier .env à la racine du projet (développement local)
#
# Pour activer la base de données : USE_DATABASE=true dans .env

import os
from dataclasses import dataclass
from pathlib import Path

# Chargement du fichier .env (si python-dotenv est installé)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv non installé → variables d'environnement système uniquement


@dataclass(frozen=True)
class DBConfig:
    use_database: bool    # False → CSV, True → base de données
    database_url: str     # URL SQLAlchemy complète
    schema: str           # Schéma SQL (ex: "public" pour PostgreSQL)


def get_config() -> DBConfig:
    """
    Lit la configuration depuis les variables d'environnement.

    Variables disponibles :
      USE_DATABASE   : "true" pour activer la BD (défaut: "false")
      DATABASE_URL   : URL de connexion SQLAlchemy
                       PostgreSQL : postgresql+psycopg2://user:pwd@host:5432/dbname
                       MySQL      : mysql+pymysql://user:pwd@host:3306/dbname
                       SQL Server : mssql+pyodbc://user:pwd@host/dbname?driver=ODBC+Driver+17+for+SQL+Server
                       SQLite     : sqlite:///./data/risk.db
      DB_SCHEMA      : Schéma de la base (défaut: "public")
    """
    return DBConfig(
        use_database=os.getenv("USE_DATABASE", "false").strip().lower() == "true",
        database_url=os.getenv("DATABASE_URL", ""),
        schema=os.getenv("DB_SCHEMA", "public"),
    )
