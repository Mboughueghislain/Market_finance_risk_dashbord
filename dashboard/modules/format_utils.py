# dashboard/modules/format_utils.py

import math
import pandas as pd
import numpy as np
import streamlit as st

from io import BytesIO
from typing import Optional, Dict, Callable



# Couleurs communes
GREEN = "#2ca02c"
RED = "#d62728"
YELLOW = "#f1c40f"
PURPLE_SOFT = "#734B81"

#============================
# Couleur de tendance
#============================

TREND_COLORS = {
    "Hausse": "#2ca02c",      # vert pour hausse
    "Baisse": "#d62728",    # rouge pour baisse
    "Stable": "#f1c40f",  # orange pour stable
}
SEUIL_STABLE = 0.005  # seuil de 0.5% pour considérer stable

# =========================
# Fonctions génériques sûres
# =========================
def _to_float_or_none(x):
    """Essaye de caster en float, sinon renvoie None."""
    try:
        if x is None:
            return None
        xf = float(x)
        if math.isnan(xf):
            return None
        return xf
    except (TypeError, ValueError):
        return None

#===========================
# Formatages génériques
#===========================
def fmt_fr(x, suffix: str = "") -> str:
    """
    Formatage français simple :
    - séparateur milliers = espace
    - séparateur décimal = virgule
    - suffix facultatif ("%", "M€", etc.)
    """
    xf = _to_float_or_none(x)
    if xf is None:
        return ""
    s = f"{xf:,.1f}"           # ex: 1,234.5
    s = s.replace(",", " ")    # 1 234.5
    s = s.replace(".", ",")    # 1 234,5
    return f"{s}{suffix}"

#===========================
# Indicateur de tendance
#===========================
def trend(pct, seuil_pct: float = 0.005) -> str:
    """
    Retourne un indicateur de tendance (smiley/icone) à partir d'une variation en décimal.
    pct = 0.012 => +1.2%
    seuil_pct : seuil à partir duquel on considère que ça monte/descend.
    """
    xf = _to_float_or_none(pct)
    if xf is None:
        return "—"

    if xf > seuil_pct:
        return "▲ Hausse"
    if xf < -seuil_pct:
        return "▼ Baisse"
    return "◆ Stable"

#===========================
# Export Excel
#===========================
def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Données") -> bytes:
    """
    Convertit un DataFrame en fichier Excel (bytes) pour st.download_button.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


# ==============================
# Formats spécifiques M€, %, pb
# ==============================

def fmt_meur(x) -> str:
    """
    Format M€ (valeur déjà exprimée en millions dans le DataFrame).
    """
    xf = _to_float_or_none(x)
    if xf is None:
        return "—"
    s = f"{xf:,.1f}".replace(",", " ").replace(".", ",")
    return f"{s} M€"

#============================ 
# Format pour variation en M€ avec signe +/-
#============================
def fmt_delta_meur(x) -> str:
    """
    Format variation en M€ avec signe +/-
    """
    xf = _to_float_or_none(x)
    if xf is None:
        return "—"
    signe = "+" if xf > 0 else ""
    s = f"{xf:,.1f}".replace(",", " ").replace(".", ",")
    return f"{signe}{s} M€"

#===========================================
# Format pour pourcentage avec signe +/-
#===========================================
def fmt_pct(x) -> str:
    """
    Format pour pourcentage (valeur déjà en % dans le DataFrame).
    """
    xf = _to_float_or_none(x)
    if xf is None:
        return "—"
    signe = "+" if xf > 0 else ""
    s = f"{xf:,.1f}".replace(",", " ").replace(".", ",")
    return f"{signe}{s} %"

def fmt_delta_pct(x) -> str:
    """
    Format pour variation en % : affiche 'Nouveau titre' si pas de VM précédente (NaN).
    """
    xf = _to_float_or_none(x)
    if xf is None:
        return "Nouveau titre"
    signe = "+" if xf > 0 else ""
    s = f"{xf:,.1f}".replace(",", " ").replace(".", ",")
    return f"{signe}{s} %"

#===========================================================
# Format pour spread en points de base (bp) avec signe +/-
#===========================================================
def fmt_bp(x) -> str:
    """
    Format pour spread en points de base (bp).
    """
    xf = _to_float_or_none(x)
    if xf is None:
        return "—"
    signe = "+" if xf > 0 else ""
    s = f"{xf:,.0f}".replace(",", " ").replace(".", ",")
    return f"{signe}{s}bp"


# ============================
# Helper de division sécurisée
# ============================
def safe_div(num, den):
    """
    Division sécurisée (retourne np.nan si division impossible).
    """
    num_f = _to_float_or_none(num)
    den_f = _to_float_or_none(den)
    if num_f is None or den_f is None or den_f == 0:
        return np.nan
    return num_f / den_f


# ============================
# Colonnes d'allocation
# ============================
def add_alloc_columns(
    df: pd.DataFrame,
    vm_fin_col: str = "VM_FIN",
    delta_vm_col: str = "Delta_VM",
) -> pd.DataFrame:
    """
    Ajoute 3 colonnes d'allocation à un DataFrame (VM déjà en M€) :
      - Alloc (%)       : vm_fin / total_vm_fin * 100
      - Alloc préc (%)  : (vm_fin - delta_vm) / total_vm_debut * 100
      - Var Alloc (%)   : Alloc (%) - Alloc préc (%)

    Le total de référence est pris sur la ligne TOTAL si elle existe,
    sinon sur la somme de toutes les lignes.
    La ligne TOTAL reçoit 100 %, 100 %, 0 %.
    """
    if vm_fin_col not in df.columns or delta_vm_col not in df.columns:
        return df

    df = df.copy()

    # Détection de la ligne TOTAL (recherche "TOTAL" dans toutes les colonnes texte)
    is_total = pd.Series(False, index=df.index)
    for col in df.columns:
        if df[col].dtype == object or str(df[col].dtype).startswith("string"):
            try:
                is_total = is_total | df[col].astype(str).str.strip().str.upper().eq("TOTAL")
            except Exception:
                pass

    vm_fin = pd.to_numeric(df[vm_fin_col], errors="coerce").fillna(0.0)
    delta_vm = pd.to_numeric(df[delta_vm_col], errors="coerce").fillna(0.0)
    vm_debut = vm_fin - delta_vm

    # Total de référence : ligne TOTAL si présente, sinon somme des lignes données
    if is_total.any():
        total_vm_fin = float(vm_fin[is_total].iloc[0])
        total_vm_debut = float(vm_debut[is_total].iloc[0])
    else:
        total_vm_fin = float(vm_fin.sum())
        total_vm_debut = float(vm_debut.sum())

    alloc = pd.Series(
        np.where(
            is_total,
            100.0,
            np.where(total_vm_fin != 0, vm_fin / total_vm_fin * 100.0, np.nan),
        ),
        index=df.index,
        dtype=float,
    )

    alloc_prec = pd.Series(
        np.where(
            is_total,
            100.0,
            np.where(total_vm_debut != 0, vm_debut / total_vm_debut * 100.0, np.nan),
        ),
        index=df.index,
        dtype=float,
    )

    df["Alloc (%)"] = alloc
    df["Δ Alloc (%)"] = np.where(is_total, 0.0, alloc - alloc_prec)

    return df

#================================================================================
# Fonction de style pour la ligne total (pour Styler.apply)
#================================================================================
def style_total_row(row, total_label="TOTAL"):
    """
    Style pour la ligne total d'un DataFrame.
    """
    if total_label in row.values:
        return ["font-weight: bold; background-color: #714A80; color:white;"] * len(row)
    return [""] * len(row) 


#================================================================================
# Fonction de style pour les variations et la ligne total (pour Styler.apply)
#================================================================================
def make_style_variation_and_total(
    delta_meur_col: str = "Δ VM (M€)",
    delta_pct_col: str = "Δ VM (%)",
    tendance_col: str = "Tendance",
    effet_invest_col: str = "Effet Investissement (%)",
    effet_marche_col: str = "Effet Marché (%)",
    #weigh_cols: tuple[str, ...] = ("Poids portefeuille (%)",),
    total_label: str = "TOTAL",
    total_cols: tuple[str, ...] = ("Classe d'actifs", "Sous-classe d'actifs"),
    stable_threshold_pct: float = 0.5,  # 0.5% (si delta_pct est en %)
    stable_threshold_meur: float = 0.05,   # 0.05 M€ = 50k€ (à ajuster)
):
    """
    Retourne une fonction compatible Styler.apply(axis=None)
    qui colore Δ et Tendance (vert/rouge/jaune) + colore la ligne TOTAL (violet).

    Hypothèse: la colonne delta_pct_col est en POURCENT (ex: 4.1 pour 4.1%).
    """

    def _style(df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame("", index=df.index, columns=df.columns)

        # --- TOTAL ---
        is_total = pd.Series(False, index=df.index)
        # colonnes spécifiquement passées (si elles existent)
        cols_to_check = [c for c in total_cols if c in df.columns] if total_cols else []
        if not cols_to_check:
            cols_to_check = [
                c for c in df.columns
                if df[c].dtype == "object" or str(df[c].dtype).startswith("string")
                ]
        for c in cols_to_check:
            is_total = is_total | (
                df[c].astype(str).str.strip().str.upper().eq(str(total_label).strip().upper())
                )

        GREEN = "#2ca02c"; RED = "#d62728"; YELLOW = "#bcbd22"
        PURPLE_SOFT = "#714A80"

        def apply_color(mask, col, color):
            if col in df.columns:
                out.loc[mask & ~is_total, col] = f"color: {color}; font-weight: 600;"
        def _to_num(s: pd.Series) -> pd.Series:
            return (
                s.astype(str)
                .str.replace("\u202f", "", regex=False)  # espaces fines
                .str.replace(" ", "", regex=False)
                .str.replace("M€", "", regex=False)
                .str.replace("€", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.replace(",", ".", regex=False)
            ).pipe(pd.to_numeric, errors="coerce")


        # --- Δ VM (%) ou Δ VM (M€) en fallback ---
        if delta_pct_col in df.columns:
            x = _to_num(df[delta_pct_col])
            stable = x.abs() < stable_threshold_pct
            hausse = x >= stable_threshold_pct
            baisse = x <= -stable_threshold_pct
            apply_color(stable, delta_pct_col, YELLOW)
            apply_color(hausse, delta_pct_col, GREEN)
            apply_color(baisse, delta_pct_col, RED)
        elif delta_meur_col in df.columns:
            x = _to_num(df[delta_meur_col])
            stable = x.abs() < stable_threshold_meur
            hausse = x >= stable_threshold_meur
            baisse = x <= -stable_threshold_meur
            apply_color(stable, delta_meur_col, YELLOW)
            apply_color(hausse, delta_meur_col, GREEN)
            apply_color(baisse, delta_meur_col, RED)
        else:
            stable = hausse = baisse = pd.Series(False, index=df.index)

        # --- Tendance ---
        apply_color(stable, tendance_col, YELLOW)
        apply_color(hausse, tendance_col, GREEN)
        apply_color(baisse, tendance_col, RED)

        # --- Δ Alloc (%) ---
        var_alloc_col = "Δ Alloc (%)"
        if var_alloc_col in df.columns:
            x_va = _to_num(df[var_alloc_col])
            stable_va = x_va.abs() < stable_threshold_pct
            hausse_va = x_va >= stable_threshold_pct
            baisse_va = x_va <= -stable_threshold_pct
            apply_color(stable_va, var_alloc_col, YELLOW)
            apply_color(hausse_va, var_alloc_col, GREEN)
            apply_color(baisse_va, var_alloc_col, RED)

        # TOTAL en violet
        if is_total.any():
            out.loc[is_total, :] = f"background-color: {PURPLE_SOFT}; color: white; font-weight: bold;"

        return out

    return _style

# =======================================================================
# Fonctions d'application des styles et formats dans les tableaux (st.dataframe)
# =======================================================================
def _auto_fmt_map(df: pd.DataFrame) -> Dict[str, Callable]:
    """
    Mapping automatique basé sur le suffixe du nom de colonne.
    Couvre tous les cas sans dépendre d'une liste fixe de noms exacts.
    """
    mapping = {}
    for col in df.columns:
        if col.endswith("(M€)"):
            # Colonnes de variation (avec signe +/-) vs valeur absolue
            if any(k in col for k in ["Δ", "Delta", "delta", "variation", "Variation"]):
                mapping[col] = fmt_delta_meur
            else:
                mapping[col] = fmt_meur
        elif col.endswith("(%)"):
            # Colonnes de variation (Δ ...) → "Nouveau titre" si NaN
            if any(k in col for k in ["Δ", "Delta", "delta"]):
                mapping[col] = fmt_delta_pct
            else:
                mapping[col] = fmt_pct
        elif col.endswith("(bp)"):
            mapping[col] = fmt_bp
    return mapping


#========================================================================================================
# Fonction pour forcer les colonnes numériques (pour que .format fonctionne bien même si données sales)
#========================================================================================================
def _ensure_numeric(df: pd.DataFrame, cols):
    """Convertit en numérique si possible (sinon laisse)."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


#================================================================================
# Fonction d'application des styles et formats dans les tableaux (st.dataframe)
#================================================================================
def apply_common_table_styles(
    df: pd.DataFrame,
    fmt_map: Optional[Dict[str, Callable]] = None,
    **kwargs,
):
    """
    - applique formats (auto si fmt_map None)
    - applique styles (variation/tendance/total via ta fonction)
    """
    df = df.copy()

    # 0) Remplace "None" / None / NaN dans les colonnes texte par "n.d." (sauf ligne TOTAL → vide)
    _none_map = {"None": "n.d.", "nan": "n.d.", "<NA>": "n.d.", "": "n.d."}
    text_cols = [c for c in df.columns if df[c].dtype == object or str(df[c].dtype).startswith("string")]
    is_total = pd.Series(False, index=df.index)
    for col in text_cols:
        is_total |= df[col].astype(str).str.strip().str.upper().eq("TOTAL")
    for col in text_cols:
        df[col] = df[col].fillna("n.d.").astype(str).replace(_none_map)
        df.loc[is_total & df[col].eq("n.d."), col] = ""

    # 1) Pré-remplissage des NaN dans les colonnes numériques avec le bon placeholder
    #    AVANT de créer le Styler, pour contourner les problèmes de na_rep avec object dtype
    for col in df.columns:
        if any(col.endswith(s) for s in ["(%)", "(M€)", "(bp)"]):
            df[col] = pd.to_numeric(df[col], errors="coerce")
            is_delta = any(k in col for k in ["Δ", "Delta", "delta"])
            placeholder = "Nouveau titre" if is_delta and col.endswith("(%)") else "—"
            df[col] = df[col].astype(object).where(df[col].notna(), placeholder)

    # 2) fmt_map auto si absent
    if fmt_map is None:
        fmt_map = _auto_fmt_map(df)

    styler = df.style

    if fmt_map:
        styler = styler.format(fmt_map, na_rep="—")

    # 3) ton style commun (TOTAL + couleurs)
    styler = styler.apply(make_style_variation_and_total(**kwargs), axis=None)

    return styler


#================================================================================
# Tableau avec TOTAL fixé en bas (toujours visible)
#================================================================================
def render_table_with_pinned_total(
    df: pd.DataFrame,
    fmt_map: Optional[Dict[str, Callable]] = None,
    max_height: int = 600,
    total_label: str = "TOTAL",
    **style_kwargs,
):
    """
    Affiche un DataFrame avec :
    - Les lignes de données dans st.dataframe (sans scrollbar si assez court)
    - La ligne TOTAL toujours visible en dessous (HTML violet)
    """
    # Détecter la ligne TOTAL
    is_total = pd.Series(False, index=df.index)
    for col in df.columns:
        try:
            is_total = is_total | df[col].astype(str).str.strip().str.upper().eq(total_label.upper())
        except Exception:
            pass

    df_data = df[~is_total].copy()
    df_total = df[is_total].copy()

    # Hauteur exacte pour afficher toutes les lignes sans scrollbar, plafonnée à max_height
    height = min((len(df_data) + 1) * 38 + 3, max_height)

    styler = apply_common_table_styles(df_data, fmt_map=fmt_map, **style_kwargs)
    st.dataframe(styler, use_container_width=True, hide_index=True, height=height)

    # Ligne TOTAL en HTML (toujours visible sous le tableau)
    if not df_total.empty:
        fmt_map_used = fmt_map if fmt_map is not None else _auto_fmt_map(df)
        row = df_total.iloc[0]
        cells_html = ""
        for col in df.columns:
            val = row.get(col, "")
            if fmt_map_used and col in fmt_map_used:
                try:
                    val = fmt_map_used[col](val)
                except Exception:
                    pass
            cells_html += (
                f'<td style="padding:6px 12px;color:white;font-weight:bold;'
                f'border-right:1px solid rgba(255,255,255,0.15);white-space:nowrap;">'
                f'{val}</td>'
            )
        total_html = (
            '<div style="width:100%;overflow-x:auto;margin-top:2px;">'
            '<table style="width:100%;border-collapse:collapse;font-size:13px;'
            'font-family:sans-serif;background-color:#714A80;border-radius:0 0 4px 4px;">'
            f'<tr>{cells_html}</tr>'
            '</table></div>'
        )
        st.markdown(total_html, unsafe_allow_html=True)
