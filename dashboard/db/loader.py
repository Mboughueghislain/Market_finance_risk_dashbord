# db/loader.py — chargement des données (CSV ou base de données)
#
# Interface unique : load_table(name) -> pd.DataFrame
#
# Le nom logique de la table est mappé vers :
#   - un fichier CSV en mode développement
#   - une table SQL en mode production
#
# Pour ajouter un nouveau jeu de données : ajouter une entrée dans TABLE_MAP.

import pandas as pd
from pathlib import Path

from db.config import get_config

# Répertoire des fichiers CSV (relatif à ce fichier : db/ → dashboard/ → projet/ → data/cleaned/)
_CSV_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cleaned"

# Colonnes à parser comme dates
_DATE_COLS = ("DATE_TRANSPA", "DATE_VALEUR", "ECHEANCE")

# Mapping nom logique → nom physique (CSV sans extension / table SQL)
TABLE_MAP: dict[str, str] = {
    "base_parent":  "base_parent_eps",
    "base_transpa": "base_transpa_eps",
    "indic_risque": "indic_risque",
    "va_sim":       "va_sim",
    "param_rrf":    "param_rrf",
    "passif_eps":   "passif_eps",
}


def load_table(name: str) -> pd.DataFrame:
    """
    Charge un jeu de données par son nom logique.

    Paramètre
    ---------
    name : str
        Nom logique défini dans TABLE_MAP (ex: "base_parent", "base_transpa").

    Retourne
    --------
    pd.DataFrame
        Données chargées avec les colonnes de dates parsées.

    Exemple
    -------
    >>> df = load_table("base_transpa")
    """
    cfg = get_config()
    physical_name = TABLE_MAP.get(name, name)

    if cfg.use_database:
        df = _load_from_db(physical_name, cfg)
    else:
        df = _load_from_csv(physical_name)

    _parse_dates(df)
    return df


# ------------------------------------------------------------------
# Backends privés
# ------------------------------------------------------------------

def _load_from_csv(table_name: str) -> pd.DataFrame:
    path = _CSV_DIR / f"{table_name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier CSV introuvable : {path}\n"
            f"Vérifiez que le fichier existe ou activez USE_DATABASE=true."
        )
    return pd.read_csv(path, sep=None, engine="python")


def _load_from_db(table_name: str, cfg) -> pd.DataFrame:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise ImportError(
            "SQLAlchemy est requis pour la connexion à la base de données.\n"
            "Installez-le avec : pip install sqlalchemy"
        ) from e

    if not cfg.database_url:
        raise ValueError(
            "DATABASE_URL n'est pas défini.\n"
            "Ajoutez-le dans votre fichier .env ou en variable d'environnement."
        )

    engine = create_engine(cfg.database_url)
    schema_prefix = f'"{cfg.schema}".' if cfg.schema else ""
    query = f'SELECT * FROM {schema_prefix}"{table_name}"'

    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


def _parse_dates(df: pd.DataFrame) -> None:
    """Parse les colonnes de dates en datetime (in-place)."""
    for col in _DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
