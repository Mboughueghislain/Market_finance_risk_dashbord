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
import streamlit.components.v1 as components


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
    "Liste des images pour Streamlit.xlsm",
    "Liste des images pour Streamlit.xlsx",
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


# ── Chargement nouveau format Excel (Libellé / Sous-Onglet) ──────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_parametres_v2(picture_dir: str) -> pd.DataFrame | None:
    """
    Charge l'Excel avec la nouvelle structure de colonnes :
    Onglet Python | Libellé onglet | Sous-Onglet Python | Périmètre |
    Nom de l'image | Titre Graphique | Ordre | extension | largeur (cm)
    """
    try:
        excel_path = _find_excel(picture_dir)
        if excel_path is None:
            return None

        df = pd.read_excel(excel_path, header=0, engine="openpyxl")

        col_map: dict[str, str] = {}
        for col in df.columns:
            c  = str(col).strip()
            cu = c.upper()
            if cu in ("NAN", ""):
                continue
            if "LIBEL" in cu and "SOUS" not in cu:
                col_map["libelle_onglet"] = c
            elif "SOUS" in cu and "ONGLET" in cu:
                col_map["sous_onglet"] = c
            elif "NOM" in cu and ("IMAGE" in cu or "L'IMAGE" in cu):
                col_map["nom_image"] = c
            elif "TITRE" in cu:
                col_map["titre"] = c
            elif cu == "ORDRE":
                col_map["ordre"] = c
            elif "EXTENSION" in cu:
                col_map["extension"] = c
            elif "LARGEUR" in cu:
                col_map["largeur"] = c

        if not {"libelle_onglet", "nom_image"}.issubset(col_map):
            return None

        df = df.rename(columns={v: k for k, v in col_map.items()})
        df = df[[c for c in col_map if c in df.columns]]
        df = df.dropna(subset=["nom_image", "libelle_onglet"])

        df["libelle_onglet"] = df["libelle_onglet"].astype(str).str.strip()
        df["nom_image"]      = df["nom_image"].astype(str).str.strip()
        df["sous_onglet"]    = df["sous_onglet"].astype(str).str.strip() if "sous_onglet" in df.columns else "N"
        df["extension"]      = (df["extension"].astype(str).str.strip().str.lower()
                                if "extension" in df.columns else "png")
        df["extension"]      = df["extension"].replace({"nan": "png", "": "png"}).fillna("png")
        df["ordre"]          = (pd.to_numeric(df["ordre"], errors="coerce").fillna(99).astype(int)
                                if "ordre" in df.columns else 99)
        df["titre"]          = df["titre"].astype(str).str.strip() if "titre" in df.columns else ""

        df = df[~df["libelle_onglet"].isin(["nan", "NAN", ""])]
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"[suivi_risques] load_parametres_v2: {e}")
        return None


# ── Rendu dynamique depuis le nouveau format Excel ────────────────────────────

def render_suivi_risques_dynamic(
    date_debut, date_fin, picture_dir: str, archives_dir: str
) -> None:
    """
    Génère les onglets et sous-onglets dynamiquement depuis l'Excel :
    - Onglets principaux  = valeurs uniques de 'Libellé onglet dans Python'
    - Sous-onglets        = valeurs de 'Sous-Onglet Python' != 'N'
    """
    df             = load_parametres_v2(picture_dir)
    available_dates = get_available_dates(archives_dir)
    date_d1        = find_closest_date(available_dates, date_fin) if available_dates else None
    archives_path  = _resolve_path(archives_dir)

    with st.expander("🔍 Diagnostic", expanded=(df is None or not available_dates)):
        if df is None:
            st.error(f"Excel introuvable ou illisible dans : {picture_dir}")
        else:
            st.success(f"Excel chargé — {len(df)} lignes, {df['libelle_onglet'].nunique()} onglets")
        if not available_dates:
            st.error(f"Aucun fichier PNG dans : {archives_dir}")
        else:
            st.info(f"Date retenue : **{date_d1 or '—'}**  |  Dates disponibles : {', '.join(available_dates[-5:])}")

    if df is None or not date_d1:
        return

    def _show_file(nom_image: str, extension: str, titre: str) -> None:
        filepath = archives_path / f"{date_d1}_{nom_image}.{extension}"
        if not filepath.exists():
            alt_ext = "html" if extension == "png" else "png"
            alt = archives_path / f"{date_d1}_{nom_image}.{alt_ext}"
            if alt.exists():
                filepath, extension = alt, alt_ext
        if titre:
            st.markdown(
                f"<p style='font-weight:600;color:#1a1a2e;margin-bottom:4px'>{titre}</p>",
                unsafe_allow_html=True,
            )
        if not filepath.exists():
            st.markdown(
                f"<div style='border:1px dashed #ccc;border-radius:6px;padding:12px;"
                f"text-align:center;color:#888;font-size:0.85em'>"
                f"Fichier non trouvé<br><code>{filepath.name}</code></div>",
                unsafe_allow_html=True,
            )
        elif extension == "html":
            components.html(filepath.read_text(encoding="utf-8", errors="replace"),
                            height=600, scrolling=True)
        else:
            st.image(str(filepath), use_container_width=True)
        st.markdown("<hr style='margin:8px 0;border-color:#e0d0f0'>", unsafe_allow_html=True)

    # Onglets principaux (ordre de première apparition dans l'Excel)
    onglets = list(dict.fromkeys(df["libelle_onglet"].tolist()))
    tabs    = st.tabs(onglets)

    for tab, onglet_label in zip(tabs, onglets):
        with tab:
            onglet_df = df[df["libelle_onglet"] == onglet_label].sort_values("ordre")
            sous = [s for s in dict.fromkeys(onglet_df["sous_onglet"].tolist())
                    if s not in ("N", "nan", "")]

            if not sous:
                for _, row in onglet_df.iterrows():
                    _show_file(str(row["nom_image"]), str(row.get("extension", "png")),
                               str(row.get("titre", "")))
            else:
                sub_tabs = st.tabs(sous)
                for sub_tab, sous_label in zip(sub_tabs, sous):
                    with sub_tab:
                        for _, row in onglet_df[onglet_df["sous_onglet"] == sous_label].iterrows():
                            _show_file(str(row["nom_image"]), str(row.get("extension", "png")),
                                       str(row.get("titre", "")))


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
    onglet_filter: str | None = None,
    selected_cantons: list[str] | None = None,
) -> None:
    """
    Affiche les graphiques d'un risque pour un canton donné (date fin uniquement).
    risque           : code RISQUE dans l'Excel et dans le nom de fichier (SDG, VALO, DEFAUT…)
    onglet_filter    : filtre sur la colonne Onglet de l'Excel (pour KPI).
    selected_cantons : cantons sélectionnés dans la sidebar (libellés dashboard).
                       Les lignes CANTON=ALL sont toujours affichées.
                       Si None, tous les cantons sont affichés.
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

        # — Sources —
        st.markdown("**Sources**")
        c1, c2 = st.columns(2)
        with c1:
            if excel_ok:
                st.success(f"Excel ✅ — {len(df_params)} ligne(s) au total")
            else:
                st.error(f"Excel ❌ — {load_error}")
            st.caption(f"Chemin : `{picture_dir}`")
        with c2:
            if archives_ok:
                st.success(f"ARCHIVES ✅ — {len(available_dates)} date(s) disponible(s)")
            else:
                st.error(f"ARCHIVES ❌ — aucun fichier trouvé")
            st.caption(f"Chemin : `{archives_dir}`")
            if available_dates:
                st.caption(f"Dernières dates : {', '.join(available_dates[-3:])}")

        st.markdown("---")

        # — Filtre actif —
        st.markdown("**Filtre actif**")
        _allowed_diag = (
            ["ALL"] + [CANTON_DISPLAY_TO_EXCEL.get(c, c.replace(" ", "_").upper()) for c in selected_cantons]
            if selected_cantons else ["(tous)"]
        )
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("RISQUE", risque)
        col_b.metric("Canton(s)", ", ".join(_allowed_diag))
        col_c.metric("Onglet filtre", onglet_filter or "—")
        col_d.metric("Date fin retenue", _fmt(date_d1))

        st.markdown("---")

        # — Fichiers attendus —
        if excel_ok and archives_ok and date_d1:
            st.markdown("**Fichiers attendus**")
            _canton_excel_diag = CANTON_DISPLAY_TO_EXCEL.get(canton_display, canton_display.replace(" ", "_").upper())
            _mask_diag = df_params["RISQUE"] == risque
            if selected_cantons:
                _mask_diag = _mask_diag & df_params["CANTON"].isin(_allowed_diag)
            if onglet_filter and "Onglet" in df_params.columns:
                _mask_diag = _mask_diag & (df_params["Onglet"].astype(str).str.strip() == onglet_filter)
            _rows_diag = df_params[_mask_diag].sort_values(["CANTON", "Ordre"])

            if _rows_diag.empty:
                st.warning("Aucune ligne trouvée dans l'Excel pour ce filtre.")
            else:
                _ap = _resolve_path(archives_dir)
                _diag_rows = []
                for _, r in _rows_diag.iterrows():
                    _nm  = str(r.get("Nom_image", "")).strip() if "Nom_image" in df_params.columns else ""
                    _ov  = str(r.get("Onglet", "")).strip()
                    _rc  = str(r.get("CANTON", "")).strip()
                    _ext = str(r.get("extension", "png")).strip().lower() or "png"
                    _base = _base_name(_nm) if _nm else f"{_rc}_{risque}_{_ov}"
                    _fname = f"{date_d1}_{_base}.{_ext}"
                    _exists = (_ap / _fname).exists()
                    _diag_rows.append({
                        "Titre": str(r.get("Titre", "")).strip() or _base,
                        "Canton": _rc,
                        "Fichier attendu": _fname,
                        "Statut": "✅" if _exists else "❌",
                    })
                import pandas as _pd_diag
                st.dataframe(
                    _pd_diag.DataFrame(_diag_rows),
                    use_container_width=True,
                    hide_index=True,
                )

    if not excel_ok:
        st.error(f"Impossible de charger le fichier Excel. Vérifiez le chemin PICTURE dans les paramètres admin.")
        return

    if not archives_ok:
        st.error(f"Aucune image trouvée dans le répertoire ARCHIVES. Vérifiez le chemin dans les paramètres admin.")
        return

    # 3. Filtre RISQUE + CANTON (+ Onglet si précisé)
    canton_excel = CANTON_DISPLAY_TO_EXCEL.get(canton_display, canton_display.replace(" ", "_").upper())

    # Cantons Excel autorisés selon la sélection sidebar
    # CANTON=ALL dans l'Excel = graphe commun à tous → toujours affiché
    if selected_cantons:
        allowed_excel = ["ALL"] + [
            CANTON_DISPLAY_TO_EXCEL.get(c, c.replace(" ", "_").upper())
            for c in selected_cantons
        ]
    else:
        allowed_excel = None  # pas de filtre → tout afficher

    mask = df_params["RISQUE"] == risque
    if allowed_excel is not None:
        mask = mask & df_params["CANTON"].isin(allowed_excel)

    if onglet_filter and "Onglet" in df_params.columns:
        mask = mask & (df_params["Onglet"].astype(str).str.strip() == onglet_filter)
    rows = df_params[mask].sort_values(["CANTON", "Ordre"])

    if rows.empty:
        st.info(f"Aucun graphique configuré pour {risque} / {canton_display}.")
        return

    # 4. En-tête période (date fin uniquement)
    st.markdown(
        f"<div style='text-align:center;font-weight:600;color:#714A80;"
        f"border-bottom:2px solid #c4a8d4;padding-bottom:4px'>"
        f"📅 Date fin — {_fmt(date_d1)}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # 5. Affichage — nom de fichier : {date}_{canton}_{risque}_{onglet}.{ext}
    archives_path = _resolve_path(archives_dir)

    def _display_file(file_path: Path, extension: str) -> None:
        """Affiche un fichier PNG ou HTML selon son extension."""
        if not file_path.exists():
            st.markdown(
                f"<div style='border:1px dashed #ccc;border-radius:6px;padding:12px;"
                f"text-align:center;color:#888;font-size:0.85em'>"
                f"Fichier non trouvé<br><code>{file_path.name}</code></div>",
                unsafe_allow_html=True,
            )
            return
        if extension == "html":
            html_content = file_path.read_text(encoding="utf-8", errors="replace")
            components.html(html_content, height=600, scrolling=True)
        else:
            st.image(str(file_path), use_container_width=True)

    for _, row in rows.iterrows():
        titre      = str(row.get("Titre", "")).strip()
        onglet_val = str(row.get("Onglet", "")).strip()
        ext        = str(row.get("extension", "png")).strip().lower() or "png"
        row_canton = str(row.get("CANTON", canton_excel)).strip()

        # Nom de base : priorité Nom_image, sinon reconstruction automatique
        nom_image = str(row.get("Nom_image", "")).strip() if "Nom_image" in df_params.columns else ""
        if nom_image:
            base = _base_name(nom_image)
        else:
            base = f"{row_canton}_{risque}_{onglet_val}"

        st.markdown(
            f"<p style='font-weight:600;color:#1a1a2e;margin-bottom:4px'>{titre or base}</p>",
            unsafe_allow_html=True,
        )

        if not date_d1:
            st.markdown(
                "<div style='border:1px dashed #ccc;border-radius:6px;padding:12px;"
                "text-align:center;color:#888;font-size:0.85em'>Aucune date disponible</div>",
                unsafe_allow_html=True,
            )
        else:
            file_path = archives_path / f"{date_d1}_{base}.{ext}"
            # Fallback : si l'extension Excel est absente, essayer png puis html
            if not file_path.exists() and ext == "png":
                alt = archives_path / f"{date_d1}_{base}.html"
                if alt.exists():
                    file_path, ext = alt, "html"
            elif not file_path.exists() and ext == "html":
                alt = archives_path / f"{date_d1}_{base}.png"
                if alt.exists():
                    file_path, ext = alt, "png"
            _display_file(file_path, ext)

        st.markdown("<hr style='margin:8px 0;border-color:#e0d0f0'>", unsafe_allow_html=True)
