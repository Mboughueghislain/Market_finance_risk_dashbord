# dashboard/modules/suivi_risques.py
"""
Suivi des Indicateurs de Risque — affichage des images par risque / canton / période.

Source de données :
  - Excel  : {suivi_risques_dir}/PICTURE/Création des images.xlsx  (feuille Parametres)
  - Images : {suivi_risques_dir}/ARCHIVES/{YYYYMMDD}_{CANTON}_{RISQUE}_{ONGLET}.png

Logique :
  - Pour chaque graphique (Titre Graphique + Ordre) filtré par RISQUE et CANTON,
    on affiche côte-à-côte l'image à date_debut et l'image à date_fin.
  - CANTON=ALL s'affiche dans tous les onglets cantons.
  - Simulation automatique si le répertoire n'est pas accessible.
"""

from __future__ import annotations

import io
import re
from pathlib import Path, PureWindowsPath

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont


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

    # Chemin UNC Windows \\serveur\... → non montable directement sous WSL.
    # On tente /mnt/<serveur>/... mais ça ne fonctionnera que si le partage
    # est monté manuellement. La solution recommandée est de mapper le partage
    # comme lettre de lecteur dans Windows (ex. Z:) et d'utiliser /mnt/z/...
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

EXCEL_FILENAME  = "Création des images.xlsx"
EXCEL_FALLBACKS = ["Creation des images.xlsx", "Création des images.xlsx", "creation des images.xlsx"]
SHEET_NAME      = "Parametres"
EXPECTED_COLS   = {"Nom_image", "RISQUE", "CANTON"}


def _find_excel(picture_dir: str) -> Path | None:
    """Cherche le fichier Excel dans le répertoire PICTURE (insensible à la casse/accentuation)."""
    base = _resolve_path(picture_dir)
    if not base.exists():
        return None
    for name in EXCEL_FALLBACKS:
        p = base / name
        if p.exists():
            return p
    # Recherche insensible à la casse parmi les fichiers .xlsx
    try:
        for f in base.glob("*.xlsx"):
            if "image" in f.name.lower():
                return f
    except Exception:
        pass
    return None


def _detect_header_row(excel_path: Path) -> int | None:
    """Détecte la ligne d'en-tête en cherchant 'Nom_image' dans les 30 premières lignes."""
    try:
        raw = pd.read_excel(excel_path, sheet_name=SHEET_NAME, header=None,
                            usecols="E:K", nrows=35, engine="openpyxl")
        for i, row in raw.iterrows():
            vals = [str(v).strip() for v in row if pd.notna(v)]
            if "Nom_image" in vals and "RISQUE" in vals:
                return int(i)
    except Exception:
        pass
    return None


@st.cache_data(ttl=300, show_spinner=False)
def load_parametres(picture_dir: str) -> pd.DataFrame | None:
    """
    Charge la feuille Parametres depuis l'Excel.
    Retourne None si le fichier n'est pas accessible.
    """
    try:
        excel_path = _find_excel(picture_dir)
        if excel_path is None:
            return None
        header_row = _detect_header_row(excel_path)
        if header_row is None:
            return None
        df = pd.read_excel(
            excel_path,
            sheet_name=SHEET_NAME,
            header=header_row,
            usecols="E:K",
            engine="openpyxl",
        )
        df.columns = ["Fichier", "Onglet", "Nom_image", "RISQUE", "CANTON", "Titre", "Ordre"]
        df = df.dropna(subset=["Nom_image", "RISQUE", "CANTON"])
        df["RISQUE"]    = df["RISQUE"].astype(str).str.strip().str.upper()
        df["CANTON"]    = df["CANTON"].astype(str).str.strip().str.upper()
        df["Ordre"]     = pd.to_numeric(df["Ordre"], errors="coerce").fillna(99).astype(int)
        df["Titre"]     = df["Titre"].fillna("").astype(str).str.strip()
        df["Nom_image"] = df["Nom_image"].astype(str).str.strip()
        df["Onglet"]    = df["Onglet"].astype(str).str.strip()
        # Exclure les lignes dont les valeurs ressemblent à des en-têtes
        df = df[~df["RISQUE"].isin(["RISQUE", "NAN", ""])]
        return df.reset_index(drop=True)
    except Exception:
        return None


# ── Gestion des dates disponibles dans ARCHIVES ───────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_available_dates(archives_dir: str) -> list[str]:
    """
    Scanne ARCHIVES et retourne les dates YYYYMMDD disponibles (triées croissant).
    """
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


# ── Génération d'images placeholder (mode simulation) ─────────────────────────

def _make_placeholder(label: str, width: int = 600, height: int = 380) -> Image.Image:
    """Génère une image PNG de remplacement avec texte centré."""
    colors = {
        "SDG":    (113, 74, 128),
        "VALO":   (74, 128, 113),
        "DEFAUT": (200, 80, 80),
    }
    risque = next((r for r in colors if r in label.upper()), None)
    bg     = colors.get(risque, (90, 90, 120)) if risque else (90, 90, 120)
    img    = Image.new("RGB", (width, height), color=bg)
    draw   = ImageDraw.Draw(img)
    # Fond légèrement plus clair en bas pour le texte
    draw.rectangle([(0, height - 80), (width, height)], fill=(240, 240, 240))
    # Texte principal
    lines = [label[i:i+50] for i in range(0, min(len(label), 150), 50)]
    y = height // 2 - len(lines) * 14
    for line in lines:
        w_txt = len(line) * 8
        draw.text(((width - w_txt) // 2, y), line, fill=(255, 255, 255))
        y += 22
    # Label placeholder en bas
    draw.text((10, height - 60), "[ SIMULATION ]", fill=(80, 80, 80))
    draw.text((10, height - 40), label[:80], fill=(60, 60, 60))
    return img


# ── Données de simulation ──────────────────────────────────────────────────────

_SIM_ROWS = [
    # SDG - ALL
    ("SDG",    "ALL",      "LIMITES", "EPS - Encours et enveloppes résiduelles par SdG",    1),
    ("SDG",    "ALL",      "SDG",     "EPS - Suivi des Sociétés de Gestion",                2),
    ("SDG",    "ALL",      "CDG",     "EPS - Suivi des SdG par catégorie de gestion",       3),
    # DEFAUT - CGP_AG
    ("DEFAUT", "CGP_AG",   "GRAPH1",  "CGP AG - KPI : Risque de Défaut global",            1),
    ("DEFAUT", "CGP_AG",   "GRAPH2",  "CGP AG - Cotation du risque ligne à ligne",         2),
    ("DEFAUT", "CGP_AG",   "GRAPH3",  "CGP AG - Répartition cotation niveau 2",            3),
    ("DEFAUT", "CGP_AG",   "GRAPH4",  "CGP AG - Répartition cotation niveau 3",            4),
    # DEFAUT - CGP_RS
    ("DEFAUT", "CGP_RS",   "GRAPH1",  "CGP RS - KPI : Risque de Défaut global",            1),
    ("DEFAUT", "CGP_RS",   "GRAPH2",  "CGP RS - Cotation du risque ligne à ligne",         2),
    ("DEFAUT", "CGP_RS",   "GRAPH3",  "CGP RS - Répartition cotation niveau 2",            3),
    ("DEFAUT", "CGP_RS",   "GRAPH4",  "CGP RS - Répartition cotation niveau 3",            4),
    # DEFAUT - BPCEM_AG
    ("DEFAUT", "BPCEM_AG", "GRAPH1",  "BPCE Mutuelle - KPI : Risque de Défaut global",     1),
    ("DEFAUT", "BPCEM_AG", "GRAPH2",  "BPCE Mutuelle - Cotation du risque ligne à ligne",  2),
    ("DEFAUT", "BPCEM_AG", "GRAPH3",  "BPCE Mutuelle - Répartition cotation niveau 2",     3),
    ("DEFAUT", "BPCEM_AG", "GRAPH4",  "BPCE Mutuelle - Répartition cotation niveau 3",     4),
    # VALO - CGP_AG
    ("VALO",   "CGP_AG",   "GRAPH1",  "CGP Actif Général - KPI : Risque de valorisation global / PRE",      1),
    ("VALO",   "CGP_AG",   "GRAPH2",  "CGP Actif Général - KPI : Risque de valorisation global / PDD",      2),
    ("VALO",   "CGP_AG",   "GRAPH3",  "CGP Actif Général - KPI : Risque de valorisation global / PV mobilisable", 3),
    ("VALO",   "CGP_AG",   "GRAPH4",  "CGP Actif Général - Risque de valorisation ligne à ligne / PDD spécifique", 4),
    ("VALO",   "CGP_AG",   "GRAPH5",  "CGP Actif Général - Concentration émetteur cotation niveau 2",       5),
    ("VALO",   "CGP_AG",   "GRAPH6",  "CGP Actif Général - Concentration émetteur cotation niveau 3",       6),
    # VALO - CGP_RS
    ("VALO",   "CGP_RS",   "GRAPH1",  "CGP Retraite Supplémentaire - KPI : Risque de valorisation global / PRE",      1),
    ("VALO",   "CGP_RS",   "GRAPH2",  "CGP Retraite Supplémentaire - KPI : Risque de valorisation global / PDD",      2),
    ("VALO",   "CGP_RS",   "GRAPH3",  "CGP Retraite Supplémentaire - KPI : Risque de valorisation global / PV mobilisable", 3),
    ("VALO",   "CGP_RS",   "GRAPH4",  "CGP Retraite Supplémentaire - Risque de valorisation ligne à ligne / PDD spécifique", 4),
    ("VALO",   "CGP_RS",   "GRAPH5",  "CGP Retraite Supplémentaire - Concentration émetteur cotation niveau 2",       5),
    ("VALO",   "CGP_RS",   "GRAPH6",  "CGP Retraite Supplémentaire - Concentration émetteur cotation niveau 3",       6),
    # VALO - BPCEM_AG
    ("VALO",   "BPCEM_AG", "GRAPH1",  "BPCE Mutuelle - KPI : Risque de valorisation global / PRE",      1),
    ("VALO",   "BPCEM_AG", "GRAPH2",  "BPCE Mutuelle - KPI : Risque de valorisation global / PDD",      2),
    ("VALO",   "BPCEM_AG", "GRAPH3",  "BPCE Mutuelle - KPI : Risque de valorisation global / PV mobilisable", 3),
    ("VALO",   "BPCEM_AG", "GRAPH4",  "BPCE Mutuelle - Risque de valorisation ligne à ligne / PDD spécifique", 4),
    ("VALO",   "BPCEM_AG", "GRAPH5",  "BPCE Mutuelle - Concentration émetteur cotation niveau 2",       5),
    ("VALO",   "BPCEM_AG", "GRAPH6",  "BPCE Mutuelle - Concentration émetteur cotation niveau 3",       6),
]

def _simulation_parametres() -> pd.DataFrame:
    return pd.DataFrame(_SIM_ROWS, columns=["RISQUE", "CANTON", "Onglet", "Titre", "Ordre"])


# ── Chargement d'une image depuis ARCHIVES ────────────────────────────────────

def _load_image(archives_dir: str, date_str: str, base: str) -> Image.Image | None:
    """Charge l'image {date_str}_{base}.png depuis ARCHIVES. None si absente."""
    try:
        path = _resolve_path(archives_dir) / f"{date_str}_{base}.png"
        if path.exists():
            return Image.open(path)
    except Exception:
        pass
    return None


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
    simulation = False
    excel_ok   = False
    load_error = ""

    # 1. Chargement des paramètres
    df_params = load_parametres(picture_dir)
    if df_params is None:
        simulation = True
        excel_ok   = False
        load_error = f"Excel introuvable ou illisible dans : {picture_dir}"
        df_params  = _simulation_parametres()
    else:
        excel_ok = True

    # 2. Dates disponibles
    available_dates = get_available_dates(archives_dir)
    archives_ok = bool(available_dates)
    if not archives_ok:
        simulation = True

    date_d0 = find_closest_date(available_dates, date_debut) if available_dates else None
    date_d1 = find_closest_date(available_dates, date_fin)   if available_dates else None

    def _fmt(d: str | None) -> str:
        if not d:
            return "—"
        return f"{d[6:8]}/{d[4:6]}/{d[:4]}"

    # 3. Filtre RISQUE + CANTON (canton exact + ALL)
    canton_excel = CANTON_DISPLAY_TO_EXCEL.get(canton_display, canton_display.replace(" ", "_").upper())
    has_nom_image = "Nom_image" in df_params.columns
    mask = (df_params["RISQUE"] == risque) & (
        df_params["CANTON"].isin([canton_excel, "ALL"])
    )
    rows = df_params[mask].sort_values("Ordre")

    # ── Diagnostic (expander) ─────────────────────────────────────────────────
    with st.expander("🔍 Diagnostic", expanded=not excel_ok or not archives_ok):
        st.markdown(f"**Excel** : {'✅ chargé' if excel_ok else '❌ ' + load_error}")
        if excel_ok:
            st.markdown(f"**Lignes dans l'Excel** : {len(df_params)}")
            st.markdown(f"**Graphiques filtrés ({risque}/{canton_display})** : {len(rows)}")
        st.markdown(f"**Répertoire ARCHIVES** : {'✅ ' + str(len(available_dates)) + ' dates disponibles' if archives_ok else '❌ aucune image PNG trouvée dans : ' + archives_dir}")
        if available_dates:
            st.markdown(f"**Dates disponibles** : {', '.join(available_dates[-5:])}" + (" ..." if len(available_dates) > 5 else ""))
        st.markdown(f"**Date début sélectionnée** → `{_fmt(date_d0)}` | **Date fin** → `{_fmt(date_d1)}`")
        if simulation:
            st.warning("Mode simulation actif — les images affichées sont des placeholders.")

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
    for _, row in rows.iterrows():
        titre = row["Titre"]
        # Utilise Nom_image de l'Excel comme source de vérité pour le nom de fichier
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
                if simulation or not date_str:
                    img = _make_placeholder(f"{date_str or '?'}_{base}")
                else:
                    img = _load_image(archives_dir, date_str, base)
                    if img is None:
                        # Affiche un message clair plutôt qu'un placeholder générique
                        st.markdown(
                            f"<div style='border:1px dashed #ccc;border-radius:6px;padding:12px;"
                            f"text-align:center;color:#888;font-size:0.85em'>"
                            f"Image non trouvée<br><code>{date_str}_{base}.png</code></div>",
                            unsafe_allow_html=True,
                        )
                        continue

                if img is not None:
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    st.image(buf.getvalue(), use_container_width=True)

        st.markdown("<hr style='margin:8px 0;border-color:#e0d0f0'>", unsafe_allow_html=True)
