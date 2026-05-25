# data/refresh_data.py
"""
Script de rafraîchissement des données.
Extrait du notebook base_parent.ipynb.
Lit les fichiers JSON depuis le dossier SAS monté et génère les CSV cleaned.
"""

import os
import sys
import shutil
import pandas as pd
from datetime import datetime
from pathlib import Path

_DEFAULT_SOURCE_DIR = "/mnt/risques/4. Risques Financiers/00-0-REPORTING/01 - HISTO SAS/0000T0"
OUT_DIR    = Path(__file__).parent / "cleaned"
RAW_DIR    = Path(__file__).parent / "raw"
BACKUP_DIR = Path(__file__).parent / "backups"


def _get_source_dir(source_dir: "str | Path | None" = None) -> Path:
    """Retourne le répertoire source : paramètre > config JSON > valeur par défaut."""
    if source_dir is not None:
        return Path(source_dir)
    try:
        from app_config import load_config  # même package
        return Path(load_config().get("source_dir", _DEFAULT_SOURCE_DIR))
    except Exception:
        return Path(_DEFAULT_SOURCE_DIR)


def _build_fichiers(source_dir: Path) -> dict:
    return {
        "base_transpa": {
            "json":    source_dir / "BT_SIM_EPS.json",
            "cleaned": OUT_DIR / "base_transpa_eps.csv",
            "raw":     RAW_DIR / "raw_base_transpa.csv",
        },
        "base_parent": {
            "json":    source_dir / "BP_SIM_EPS.json",
            "cleaned": OUT_DIR / "base_parent_eps.csv",
            "raw":     RAW_DIR / "raw_base_parent.csv",
        },
        "passif": {
            "json":    source_dir / "PASSIF_SIM_EPS.json",
            "cleaned": OUT_DIR / "passif_eps.csv",
            "raw":     RAW_DIR / "raw_passif.csv",
        },
        "param_rrf": {
            "json":    source_dir / "PARAM_RRF.json",
            "cleaned": OUT_DIR / "param_rrf.csv",
            "raw":     RAW_DIR / "raw_param_rrf.csv",
        },
        "va_sim": {
            "json":    source_dir / "VA_SIM_EPS.json",
            "cleaned": OUT_DIR / "va_sim.csv",
            "raw":     RAW_DIR / "raw_va_sim.csv",
        },
        "indic_risque": {
            "json":    source_dir / "INDICATEURS_RISQUE.json",
            "cleaned": OUT_DIR / "indic_risque.csv",
            "raw":     RAW_DIR / "raw_indicateurs_risque.csv",
        },
    }


# Rétrocompatibilité : FICHIERS et SOURCE_DIR gardent les valeurs par défaut au chargement du module
SOURCE_DIR = _get_source_dir()
FICHIERS   = _build_fichiers(SOURCE_DIR)


def _fmt_size(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size} o"
    elif size < 1024 ** 2:
        return f"{size / 1024:.2f} Ko"
    return f"{size / 1024 ** 2:.2f} Mo"


def _process_base_transpa(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["ID"] != "TRANSFERT"].copy()
    for col in ["DATE_VALEUR", "DATE_TRANSPA"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    return df


def _process_base_parent(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["DATE_VALEUR", "DATE_TRANSPA"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    return df


def _process_indic_risque(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.str.strip()
    if "DATE_TRANSPA" in df.columns:
        df["DATE_TRANSPA"] = pd.to_datetime(df["DATE_TRANSPA"], dayfirst=True, errors="coerce")
    return df


def _process_generic(df: pd.DataFrame) -> pd.DataFrame:
    """Traitement minimal pour passif, param_rrf, va_sim."""
    return df


_PROCESSORS = {
    "base_transpa": _process_base_transpa,
    "base_parent":  _process_base_parent,
    "indic_risque": _process_indic_risque,
    "passif":       _process_generic,
    "param_rrf":    _process_generic,
    "va_sim":       _process_generic,
}


def _backup_file(cleaned_path: Path, keep: int, log=print) -> None:
    """Copie le CSV actuel dans BACKUP_DIR avec horodatage, puis purge les anciens."""
    if not cleaned_path.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M")
    dst = BACKUP_DIR / f"{cleaned_path.stem}_{ts}.csv"
    shutil.copy2(cleaned_path, dst)
    log(f"  📦 Backup : {dst.name}")

    # Purge : garder seulement les `keep` plus récents pour ce fichier
    if keep > 0:
        pattern = f"{cleaned_path.stem}_*.csv"
        existing = sorted(BACKUP_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
        for old in existing[:-keep]:
            old.unlink()
            log(f"  🗑️  Suppression ancien backup : {old.name}")


def refresh_one(name: str, log=print, source_dir: "str | Path | None" = None,
                backup: bool = False, backup_keep: int = 5) -> dict:
    """
    Rafraîchit un fichier. Retourne un dict avec status, rows, size, error.
    backup      : si True, sauvegarde le CSV actuel avant écrasement
    backup_keep : nombre de backups à conserver par fichier (0 = illimité)
    """
    fichiers = _build_fichiers(_get_source_dir(source_dir))
    cfg = fichiers[name]
    json_path = cfg["json"]

    if not json_path.exists():
        return {"status": "error", "error": f"Fichier source introuvable : {json_path}"}

    try:
        log(f"  Lecture de {json_path.name}...")
        df = pd.read_json(json_path)

        log(f"  Traitement ({len(df):,} lignes)...")
        df = _PROCESSORS[name](df)

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)

        # Backup avant écrasement
        if backup:
            _backup_file(cfg["cleaned"], keep=backup_keep, log=log)

        df.to_csv(cfg["raw"],     index=False, encoding="utf-8-sig")
        df.to_csv(cfg["cleaned"], index=False, encoding="utf-8-sig")

        size = _fmt_size(cfg["cleaned"])
        log(f"  ✓ {cfg['cleaned'].name} — {len(df):,} lignes — {size}")
        return {"status": "ok", "rows": len(df), "size": size}

    except Exception as e:
        return {"status": "error", "error": str(e)}


def refresh_all(log=print, source_dir: "str | Path | None" = None,
                backup: bool = False, backup_keep: int = 5) -> dict:
    """Rafraîchit tous les fichiers. Retourne un dict name -> résultat."""
    fichiers = _build_fichiers(_get_source_dir(source_dir))
    results = {}
    for name in fichiers:
        log(f"\n[{name}]")
        results[name] = refresh_one(name, log=log, source_dir=source_dir,
                                    backup=backup, backup_keep=backup_keep)
    return results


def source_available(source_dir: "str | Path | None" = None) -> bool:
    return _get_source_dir(source_dir).exists()


if __name__ == "__main__":
    if not source_available():
        print(f"ERREUR : dossier source inaccessible ({SOURCE_DIR})", file=sys.stderr)
        sys.exit(1)
    results = refresh_all()
    errors = [n for n, r in results.items() if r["status"] == "error"]
    if errors:
        print(f"\nÉchecs : {errors}", file=sys.stderr)
        sys.exit(1)
    print("\nTous les fichiers ont été mis à jour avec succès.")
