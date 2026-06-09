# dashboard/modules/suivi_risques.py
"""
Suivi des Indicateurs de Risque — affichage des images par risque / canton / période.

Source de données :
  - Excel  : {picture_dir}/Création des images.xlsm  (feuille Parametres)
  - Images : {archives_dir}/{YYYYMMDD}_{CANTON}_{RISQUE}_{ONGLET}.png
"""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

import pandas as pd
import streamlit as st


# ── Mapping CANTON Excel → libellé dashboard ──────────────────────────────────
CANTON_EXCEL_TO_DISPLAY: dict[str, str] = {
    "CGP_AG":   "CGP AG",
    "CGP_RS":   "CGP RS",
    "BPCEM_AG": "BPCEM AG",
    "ALL":      "ALL",
}
CANTON_DISPLAY_TO_EXCEL: dict[str, str] = {
    v: k for k, v in CANTON_EXCEL_TO_DISPLAY.items() if k != "ALL"
}


def _resolve_path(raw: str) -> Path:
    """Convertit un chemin Windows (UNC ou lettre de lecteur) en Path utilisable sous WSL/Linux."""
    raw = raw.strip()

    # Chemin lettre de lecteur Windows : Z:\foo\bar → /mnt/z/foo/bar
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        drive = raw[0].lower()
        rest  = raw[2:].replace("\\", "/").lstrip("/")
        return Path(f"/mnt/{drive}/{rest}")

    # Chemin UNC Windows → nécessite un montage via fstab (voir README)
    if raw.startswith("\\\\") or raw.startswith("//"):
        try:
            posix = PureWindowsPath(raw).as_posix().lstrip("/")
        except Exception:
            posix = raw.lstrip("/\\")
        wsl = Path("/mnt") / posix
        if wsl.exists():
            return wsl
        return Path(raw)

    return Path(raw)


# ── Chargement de la feuille Parametres ───────────────────────────────────────

EXCEL_FALLBACKS = [
    "Création des images.xlsm",
    "Creation des images.xlsm",
    "Création des images.xlsx",
    "Creation des images.xlsx",
]
SHEET_NAMES = ["Parametres", "Paramètres", "parametres", "PARAMETRES", "Parametre", "Sheet1"]


def _find_excel(picture_dir: str) -> Path | None:
    """Cherche le fichier Excel (.xlsm ou .xlsx) dans le répertoire PICTURE."""
    base = _resolve_path(picture_dir)
    if not base.exists():
        return None
    for name in EXCEL_FALLBACKS:
        p = base / name
        if p.exists():
            return p
    try:
        for ext in ("*.xlsm", "*.xlsx"):
            for f in base.glob(ext):
                if "image" in f.name.lower():
                    return f
    except Exception:
        pass
    return None


def _detect_sheet_and_header(excel_path: Path) -> tuple[str, int] | None:
    """
    Détecte automatiquement la feuille et la ligne d'en-tête.
    Cherche une ligne contenant 'RISQUE' et 'CANTON' parmi les 40 premières.
    """
    import openpyxl
    try:
        wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
        actual_sheets = wb.sheetnames
        wb.close()
    except Exception:
        return None

    candidates = [s for s in SHEET_NAMES if s in actual_sheets]
    candidates += [s for s in actual_sheets if s not in candidates]

    for sheet in candidates:
        try:
            raw = pd.read_excel(excel_path, sheet_name=sheet, header=None,
                                engine="openpyxl", nrows=40)
            for i, row in raw.iterrows():
                vals = [str(v).strip().upper() for v in row if pd.notna(v) and str(v).strip()]
                if "RISQUE" in vals and "CANTON" in vals:
                    return (sheet, int(i))
        except Exception:
            continue
    return None


@st.cache_data(ttl=300, show_spinner=False)
def load_parametres(picture_dir: str) -> pd.DataFrame | None:
    """
    Charge la feuille Parametres depuis l'Excel.
    Détecte automatiquement le nom de la feuille, la ligne d'en-tête et les colonnes.
    Retourne None si le fichier n'est pas accessible.
    """
    try:
        excel_path = _find_excel(picture_dir)
        if excel_path is None:
            return None

        result = _detect_sheet_and_header(excel_path)
        if result is None:
            return None
        sheet_name, header_row = result

        df = pd.read_excel(excel_path, sheet_name=sheet_name,
                           header=header_row, engine="openpyxl")

        # Détection dynamique des colonnes par nom
        col_map: dict[str, str] = {}
        for col in df.columns:
            c  = str(col).strip()
            cu = c.upper()
            if cu == "RISQUE":
                col_map["RISQUE"] = c
            elif cu == "CANTON":
                col_map["CANTON"] = c
            elif "IMAGE" in cu:
                col_map["Nom_image"] = c
            elif "TITRE" in cu:
                col_map["Titre"] = c
            elif cu == "ORDRE":
                col_map["Ordre"] = c
            elif cu == "ONGLET":
                col_map["Onglet"] = c
            elif cu == "FICHIER":
                col_map["Fichier"] = c

        if not {"RISQUE", "CANTON", "Nom_image"}.issubset(col_map):
            return None

        inv = {v: k for k, v in col_map.items()}
        df = df[[c for c in inv if c in df.columns]].rename(columns=inv)

        df = df.dropna(subset=["Nom_image", "RISQUE", "CANTON"])
        df["RISQUE"]    = df["RISQUE"].astype(str).str.strip().str.upper()
        df["CANTON"]    = df["CANTON"].astype(str).str.strip().str.upper()
        df["Nom_image"] = df["Nom_image"].astype(str).str.strip()
        df["Ordre"]     = pd.to_numeric(df.get("Ordre", 99), errors="coerce").fillna(99).astype(int)
        df["Titre"]     = df["Titre"].fillna("").astype(str).str.strip() if "Titre" in df.columns else ""
        df["Onglet"]    = df["Onglet"].astype(str).str.strip() if "Onglet" in df.columns else ""

        df = df[~df["RISQUE"].isin(["RISQUE", "NAN", ""])]
        return df.reset_index(drop=True)
    except Exception:
        return None


# ── Gestion des dates disponibles dans ARCHIVES ───────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_available_dates(archives_dir: str) -> list[str]:
    """Scanne ARCHIVES et retourne les dates YYYYMMDD disponibles (triées croissant)."""
    try:
        path = _resolve_path(archives_dir)
        dates: set[str] = set()
        for f in path.glob("*.png"):
            m = re.match(r"^(\d{8})_", f.name)
            if m:
                dates.add(m.group(1))
        return sorted(dates)
    except Exception:
        return []


def find_closest_date(available: list[str], target) -> str | None:
    """Retourne la date disponible la plus récente ≤ target (format YYYYMMDD)."""
    if not available:
        return None
    try:
        target_str = pd.to_datetime(target).strftime("%Y%m%d")
    except Exception:
        return None
    candidates = [d for d in available if d <= target_str]
    return candidates[-1] if candidates else available[0]


def _base_name(nom_image: str) -> str:
    """Extrait la partie sans date : '20260331_CGP_AG_DEFAUT_GRAPH1' → 'CGP_AG_DEFAUT_GRAPH1'."""
    m = re.match(r"^\d{8}_(.+)$", nom_image.strip())
    return m.group(1) if m else nom_image.strip()


# ── Rendu principal ────────────────────────────────────────────────────────────

def render_suivi_risques_canton(
    risque: str,
    canton_display: str,
    date_debut,
    date_fin,
    picture_dir: str,
    archives_dir: str,
) -> None:
    """
    Affiche les graphiques d'un risque pour un canton donné.
    Chaque graphique est montré en 2 colonnes : date_debut (gauche) / date_fin (droite).
    """
    excel_ok   = False
    load_error = ""

    # 1. Chargement des paramètres
    df_params = load_parametres(picture_dir)
    if df_params is None:
        load_error = f"Excel introuvable ou illisible dans : {picture_dir}"
    else:
        excel_ok = True

    # 2. Dates disponibles
    available_dates = get_available_dates(archives_dir)
    archives_ok     = bool(available_dates)

    date_d0 = find_closest_date(available_dates, date_debut) if available_dates else None
    date_d1 = find_closest_date(available_dates, date_fin)   if available_dates else None

    def _fmt(d: str | None) -> str:
        return f"{d[6:8]}/{d[4:6]}/{d[:4]}" if d else "—"

    # ── Diagnostic ────────────────────────────────────────────────────────────
    with st.expander("🔍 Diagnostic", expanded=not excel_ok or not archives_ok):
        st.markdown(f"**Excel** : {'✅ chargé' if excel_ok else '❌ ' + load_error}")
        if excel_ok:
            canton_excel_diag = CANTON_DISPLAY_TO_EXCEL.get(canton_display, canton_display.replace(" ", "_").upper())
            mask_diag = (df_params["RISQUE"] == risque) & (df_params["CANTON"].isin([canton_excel_diag, "ALL"]))
            st.markdown(f"**Lignes dans l'Excel** : {len(df_params)}")
            st.markdown(f"**Graphiques filtrés ({risque}/{canton_display})** : {mask_diag.sum()}")
        archives_msg = f"✅ {len(available_dates)} dates disponibles" if archives_ok else f"❌ aucune image PNG trouvée dans : {archives_dir}"
        st.markdown(f"**Répertoire ARCHIVES** : {archives_msg}")
        if available_dates:
            st.markdown(f"**Dates disponibles** : {', '.join(available_dates[-5:])}" + (" ..." if len(available_dates) > 5 else ""))
        st.markdown(f"**Date début** → `{_fmt(date_d0)}` | **Date fin** → `{_fmt(date_d1)}`")

    if not excel_ok:
        st.error(f"Impossible de charger le fichier Excel. Vérifiez le chemin PICTURE dans les paramètres admin.")
        return

    if not archives_ok:
        st.error(f"Aucune image trouvée dans le répertoire ARCHIVES. Vérifiez le chemin dans les paramètres admin.")
        return

    # 3. Filtre RISQUE + CANTON
    canton_excel  = CANTON_DISPLAY_TO_EXCEL.get(canton_display, canton_display.replace(" ", "_").upper())
    has_nom_image = "Nom_image" in df_params.columns
    mask  = (df_params["RISQUE"] == risque) & (df_params["CANTON"].isin([canton_excel, "ALL"]))
    rows  = df_params[mask].sort_values("Ordre")

    if rows.empty:
        st.info(f"Aucun graphique configuré pour {risque} / {canton_display}.")
        return

    # 4. En-tête période
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        st.markdown(
            f"<div style='text-align:center;font-weight:600;color:#714A80;"
            f"border-bottom:2px solid #714A80;padding-bottom:4px'>"
            f"📅 Date début — {_fmt(date_d0)}</div>",
            unsafe_allow_html=True,
        )
    with col_h2:
        st.markdown(
            f"<div style='text-align:center;font-weight:600;color:#714A80;"
            f"border-bottom:2px solid #c4a8d4;padding-bottom:4px'>"
            f"📅 Date fin — {_fmt(date_d1)}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # 5. Affichage par paire
    archives_path = _resolve_path(archives_dir)
    for _, row in rows.iterrows():
        titre = row["Titre"]
        if has_nom_image and str(row.get("Nom_image", "")).strip():
            base = _base_name(str(row["Nom_image"]))
        else:
            onglet = str(row.get("Onglet", "")).strip()
            base   = f"{canton_excel}_{risque}_{onglet}"

        st.markdown(
            f"<p style='font-weight:600;color:#1a1a2e;margin-bottom:4px'>{titre}</p>",
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)
        for col, date_str in [(col1, date_d0), (col2, date_d1)]:
            with col:
                if not date_str:
                    st.markdown(
                        "<div style='border:1px dashed #ccc;border-radius:6px;padding:12px;"
                        "text-align:center;color:#888;font-size:0.85em'>Aucune date disponible</div>",
                        unsafe_allow_html=True,
                    )
                    continue
                img_path = archives_path / f"{date_str}_{base}.png"
                if img_path.exists():
                    st.image(str(img_path), use_container_width=True)
                else:
                    st.markdown(
                        f"<div style='border:1px dashed #ccc;border-radius:6px;padding:12px;"
                        f"text-align:center;color:#888;font-size:0.85em'>"
                        f"Image non trouvée<br><code>{date_str}_{base}.png</code></div>",
                        unsafe_allow_html=True,
                    )

        st.markdown("<hr style='margin:8px 0;border-color:#e0d0f0'>", unsafe_allow_html=True)
