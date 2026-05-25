# dashboard/modules/risque_action.py
"""
Onglet : Risque Action

Objectif :
- Garder la même philosophie de tableaux que Risque Spread
  (Vue par Type de groupe / Type d'émetteur, TOTAL, styles, export Excel)
- MAIS organiser la page autour de la concentration :

  1) Risque de concentration par émetteur / groupe
     - Top 10 (tableau avec VM début, VM fin, Δ, %, tendance, poids)
     - Treemap (heatmap) à côté

  2) Risque de concentration géographique
     - Top 10 (même structure de tableau)
     - Carte du monde (bulles), vue par défaut Europe, radio pour changer la vue

  3) Risque de concentration par secteur
     - Tableau complet (pas limité au Top 10)
     - Treemap à côté
"""

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from typing import Optional, List, Tuple

from modules.format_utils import (
    trend,
    fmt_meur,
    fmt_delta_meur,
    fmt_pct,
    df_to_excel_bytes,
    style_total_row,
    apply_common_table_styles,
    render_static_dataframe,
    add_alloc_columns,
)

# ==========================================================
# Helpers
# ==========================================================


def _pick_first_existing_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """
    Retourne le premier nom de colonne présent dans le DataFrame parmi une liste de candidats.
    Permet de rendre le code robuste aux variations de noms (PAYS / COUNTRY, SECTEUR / SECTOR, etc.).
    """
    for c in candidates:
        if c in df.columns:
            return c
    return None


# Palette claire pour les treemaps (fond blanc, couleurs distinctes)
_TREEMAP_PALETTE = [
    "#714A80",  # violet (couleur principale du dashboard)
    "#2C6FAC",  # bleu
    "#3A9E5F",  # vert
    "#D4704B",  # orange
    "#8B6BB5",  # violet clair
    "#2A9BAB",  # cyan
    "#B55C3A",  # brun-rouge
    "#C95B8B",  # rose
    "#4D8B7A",  # vert foncé
    "#7B8B3A",  # olive
    "#5B7AB5",  # bleu ardoise
    "#B58B3A",  # doré
]


def _treemap_vm(
    df: pd.DataFrame,
    path_cols: List[str],
    value_col: str,
    title: str,
) -> px.treemap:
    """
    Construit treemap standarisé sur une VM (M€) avec :
    - hiérarchie path_cols
    - VM en hover + % du total + % du parent
    - palette claire pour éviter les fonds sombres
    """
    df = df.copy()
    for col in path_cols:
        df[col] = df[col].fillna("n.d.").astype(str)

    fig = px.treemap(
        df,
        path=path_cols,
        values=value_col,
        title=title,
        color_discrete_sequence=_TREEMAP_PALETTE,
    )

    fig.update_traces(
        textfont=dict(size=10, color="white"),
        marker=dict(line=dict(width=1, color="white")),
        hovertemplate=(
            "<b>%{label}</b><br>"
            "<b>VM : %{value:,.1f} M€</b><br>"
            "<b>Part du total : %{percentRoot:.1%}</b><br>"
            "<b>Part du parent : %{percentParent:.1%}</b><extra></extra>"
        ),
    )

    fig.update_layout(margin=dict(t=30, l=10, r=10, b=10))

    return fig

def _to_date(d) -> Optional[pd.Timestamp]:
    """Conversion sécurisée en Timestamp, retourne None si impossible."""
    try:
        return pd.to_datetime(d)
    except Exception:
        return None


def _prepare_action_base(
    df_selection: pd.DataFrame,
    date_debut,
    date_fin,
) -> Optional[Tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]]:
    """
    Prépare la base pour le Risque Action :
    - copie df_selection
    - applique le filtre RSQ_FIN_ACTION == 1 si la colonne existe
    - calcule d0 (date début effective) et d1 (date fin effective) à partir de DATE_TRANSPA
    - retourne (dff, d0, d1)

    dff : DataFrame filtré Action avec DATE_TRANSPA au format date.
    d0  : date réelle de début <= date_debut
    d1  : date réelle de fin   <= date_fin
    """
    if df_selection is None or df_selection.empty:
        return None

    dff = df_selection.copy()

    # Filtre Action si la colonne existe
    flag_col = "RSQ_FIN_ACTION"
    if flag_col in dff.columns:
        dff = dff[dff[flag_col].astype(str) == "1"].copy()
        if dff.empty:
            return None

    if "DATE_TRANSPA" not in dff.columns:
        st.warning("Colonne DATE_TRANSPA absente : impossible de positionner le Risque Action dans le temps.")
        return None

    dff["DATE_TRANSPA"] = pd.to_datetime(dff["DATE_TRANSPA"], errors="coerce").dt.date

    d0_target = _to_date(date_debut)
    d1_target = _to_date(date_fin)
    if d0_target is None or d1_target is None:
        return None

    d0_target = d0_target.date()
    d1_target = d1_target.date()

    d0 = dff.loc[dff["DATE_TRANSPA"] <= d0_target, "DATE_TRANSPA"].max()
    d1 = dff.loc[dff["DATE_TRANSPA"] <= d1_target, "DATE_TRANSPA"].max()

    if pd.isna(d0) or pd.isna(d1):
        return None

    if "VM_INIT" not in dff.columns:
        st.warning("Colonne VM_INIT absente : impossible de calculer les expositions.")
        return None

    # On sécurise VM_INIT en numérique
    dff["VM_INIT"] = pd.to_numeric(dff["VM_INIT"], errors="coerce").fillna(0.0)

    return dff, pd.to_datetime(d0), pd.to_datetime(d1)


def _build_concentration_table(
    dff: pd.DataFrame,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
    group_col: str,
    top_n: Optional[int],
) -> pd.DataFrame:
    """
    Construit un tableau de concentration par group_col, avec :
      - VM_DEBUT (M€)
      - VM_FIN   (M€)
      - Delta_VM (M€)
      - Delta_VM_pct (%)
      - Tendance (fonction trend)

    Si top_n est fourni, on limite aux top_n plus gros VM_FIN, puis on ajoute une ligne TOTAL.
    Sinon, on garde toutes les lignes + TOTAL.

    Retourne un DataFrame prêt pour mise en forme (Libellé, VM_DEBUT, VM_FIN, Delta_VM, Delta_VM_pct, Tendance).
    """
    # Filtrage aux deux dates
    dff = dff.copy()
    dff["DATE_TRANSPA"] = pd.to_datetime(dff["DATE_TRANSPA"], errors="coerce")
    
    d0 = pd.to_datetime(d0)
    d1 = pd.to_datetime(d1)
    
    # Sous-ensesemble des données des deux dates
    df0 = dff[dff["DATE_TRANSPA"].dt.date == d0.date()].copy()
    df1 = dff[dff["DATE_TRANSPA"].dt.date == d1.date()].copy()
    
    # Si on n'a pas de données aux deux dates, on renvoie un DataFrame vide avec les bonnes colonnes
    if df0.empty and df1.empty:
        return pd.DataFrame(columns=[
            "Libellé", 
            "VM_DEBUT", 
            "VM_FIN", 
            "Delta_VM",
            "Delta_VM_pct",
            "Tendance",
            "LIBELLE",
            "SOUS_SECTEUR_EPS",
            ]
        )
        
    grp = group_col

    # Normalisation : NaN, chaînes vides, espaces → "n.d." pour éviter les doublons
    for sub in [df0, df1]:
        sub[grp] = (
            sub[grp]
            .fillna("n.d.")
            .astype(str)
            .str.strip()
            .replace("", "n.d.")
        )

    # =========================================
    # Agregations VM_DEBUT et VM_FIN (en €)
    # =========================================

    
    # VM début et fin
    debut = (
        df0.groupby(grp, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_DEBUT")
    )
    fin = (
        df1.groupby(grp, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_FIN")
    )

    res = (pd.concat([debut, fin], axis=1)
           .fillna(0.0)
           .reset_index()
           )
    # On renomme la clé de groupby en "Libellé"
    res =res.rename(columns={grp: "Libellé"})
    
    # Ici tres important pour notre treemap : on  force "Libellé" en string simple sans NaN ni objets bizarres
    res["Libellé"] = res["Libellé"].fillna("n.d.").astype(str)

    # Δ VM et %
    res["Delta_VM"] = res["VM_FIN"] - res["VM_DEBUT"]
    res["Delta_VM_pct"] = np.where(
        res["VM_DEBUT"] != 0,
        res["Delta_VM"] / res["VM_DEBUT"],
        np.nan,
    )
    res["Tendance"] = res["Delta_VM_pct"].apply(trend)
    
    # colonnes descriptives (LIBELLE, SOUS_SECTEUR_EPS) prises à d1
    extra_cols = []
    if "LIBELLE" in df1.columns:
        extra_cols.append("LIBELLE")
    if "SOUS_SECTEUR_EPS" in df1.columns:
        extra_cols.append("SOUS_SECTEUR_EPS")
        
    if extra_cols:
        desc = (
            df1.groupby(grp, dropna=False)[extra_cols]
            .first()
            .reset_index()
        )
        # Dans desc, la clé s'appèlle encore grp, on merge or dans res, on a renommé grp par "Libellé"
        res = res.merge(
            desc,
            left_on="Libellé", # clé coté res
            right_on=grp,   # clé coté desc
            how="left",
        )
        res = res.drop(columns=[grp])

    total_vm_fin = float(res["VM_FIN"].sum())

    # Passage en M€ et % pour l'affichage
    view = res.copy()
    for c in ["VM_DEBUT", "VM_FIN", "Delta_VM"]:
        view[c] = view[c] / 1e6
    view["Delta_VM_pct"] = view["Delta_VM_pct"] * 100.0

    # Tri sur VM_FIN décroissante
    view = view.sort_values("VM_FIN", ascending=False)

    # Top N avec ligne Autres pour le reste
    if top_n is not None:
        top = view.head(top_n).copy()
        autres = view.iloc[top_n:].copy()
        if not autres.empty:
            a_vm_debut = autres["VM_DEBUT"].sum()
            a_vm_fin   = autres["VM_FIN"].sum()
            a_delta    = autres["Delta_VM"].sum()
            a_pct      = (a_delta / a_vm_debut * 100.0) if a_vm_debut != 0 else np.nan
            autres_row = pd.DataFrame([{
                "Libellé": "Autres",
                "VM_DEBUT": a_vm_debut,
                "VM_FIN": a_vm_fin,
                "Delta_VM": a_delta,
                "Delta_VM_pct": a_pct,
                "Tendance": trend(a_pct / 100.0 if pd.notna(a_pct) else np.nan),
            }])
            view = pd.concat([top, autres_row], ignore_index=True)
        else:
            view = top

    # Ligne TOTAL
    total_row = pd.DataFrame([{
        "Libellé": "TOTAL",
        "VM_DEBUT": res["VM_DEBUT"].sum() / 1e6,
        "VM_FIN": total_vm_fin / 1e6,
        "Delta_VM": (res["Delta_VM"].sum()) / 1e6,
        "Delta_VM_pct": (
            (res["Delta_VM"].sum() / res["VM_DEBUT"].sum() * 100.0)
            if res["VM_DEBUT"].sum() != 0
            else np.nan
        ),
        "Tendance": trend(
            (res["Delta_VM"].sum() / res["VM_DEBUT"].sum())
            if res["VM_DEBUT"].sum() != 0
            else np.nan
        ),
    }])

    view = pd.concat([view, total_row], ignore_index=True)
    view = add_alloc_columns(view, vm_fin_col="VM_FIN", delta_vm_col="Delta_VM")

    return view


# ==========================================================
# Render principal
# ==========================================================

def build_risque_action_issuer_section(
    dff: pd.DataFrame,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
    choix_dim_affichage: str,
):
    """
    Construit les éléments de la section 'Concentration par émetteur / groupe'
    sans appel à Streamlit.

    Retourne :
      - label_header : nom de la colonne de libellé pour affichage
      - df_aff       : DataFrame Top 10 + TOTAL (colonnes déjà renommées & ordonnées)
      - fig_treemap  : figure Plotly de la treemap (ou None si non construite)
    """

    # 1) Choix des colonnes candidates selon le radio
    if choix_dim_affichage == "Type de groupe":
        issuer_candidates = ["LIB_GROUPE", "GROUPE", "EMETTEUR_GROUPE"]
        label_header = "Libellé du groupe"
    else:
        issuer_candidates = ["LIB_EMETTEUR", "EMETTEUR", "NOM_EMETTEUR"]
        label_header = "Libellé de l'émetteur"

    issuer_col = _pick_first_existing_col(dff, issuer_candidates)
    if issuer_col is None:
        # On retourne None pour signaler qu'on ne peut rien faire
        return None, None, None

    # 2) Top 10 + base complète via la fonction générique
    df_conc_issuer_top10 = _build_concentration_table(
        dff=dff,
        d0=d0,
        d1=d1,
        group_col=issuer_col,
        top_n=10,  # Top 10
    )

    df_conc_issuer_all = _build_concentration_table(
        dff=dff,
        d0=d0,
        d1=d1,
        group_col=issuer_col,
        top_n=None,  # toutes les lignes
    )

    # 3) DataFrame d'affichage (Top 10)
    df_aff = df_conc_issuer_top10.copy()
    df_aff = df_aff.rename(columns={
        "Libellé": label_header,  # libellé dynamique
        "VM_FIN": "VM (M€)",
        "Delta_VM": "Δ VM (M€)",
        "Delta_VM_pct": "Δ VM (%)",
    })

    cols_order = [
        label_header,
        "VM (M€)",
        "Δ VM (M€)",
        "Δ VM (%)",
        "Tendance",
        "Alloc (%)",
        "Δ Alloc (%)",
    ]
    df_aff = df_aff[[c for c in cols_order if c in df_aff.columns]]

    # 4) Treemap : on enlève TOTAL + VM_FIN <= 0
    treemap_df = df_conc_issuer_all[df_conc_issuer_all["Libellé"] != "TOTAL"].copy()
    treemap_df = treemap_df[treemap_df["VM_FIN"] > 0]

    fig_treemap = None
    if not treemap_df.empty:
        fig_treemap = _treemap_vm(
            treemap_df,
            path_cols=["Libellé"],
            value_col="VM_FIN",
            title=None,
        )
        fig_treemap.update_traces(
            customdata=treemap_df[["VM_FIN"]].to_numpy(),
            texttemplate="<b>%{label}</b><br>%{percentRoot:.1%}",
            textfont=dict(size=10),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "<b>VM : %{value:,.1f} M€</b><br>"
                "<b>Part du total : %{percentRoot:.1%}</b><br>"
                "<b>Part du parent : %{percentParent:.1%}</b><extra></extra>"
            ),
        )
        fig_treemap.update_layout(margin=dict(t=30, l=10, r=10, b=10))

    return label_header, df_aff, fig_treemap

def build_risque_action_geo_section(
    dff: pd.DataFrame,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
    geo_scope: str,  # ex: "europe", "world", ...
):
    """
    Construit la section 'Risque de concentration géographique' sans Streamlit.

    Retourne :
      - df_aff_geo : DataFrame Top 10 (table d'affichage)
      - fig_map    : figure Plotly scatter_geo (ou None si non disponible)
    """

    geo_candidates = ["PAYS", "PAYS_EMETTEUR", "COUNTRY", "COUNTRY_OF_RISK", "ZONE", "ZONE_ACTION"]
    geo_col = _pick_first_existing_col(dff, geo_candidates)

    if geo_col is None:
        return None, None

    # Top 10 (M€ déjà dans _build_concentration_table)
    df_conc_geo_top10 = _build_concentration_table(
        dff=dff,
        d0=d0,
        d1=d1,
        group_col=geo_col,
        top_n=10,
    )

    df_aff_geo = df_conc_geo_top10.copy()
    df_aff_geo = df_aff_geo.rename(columns={
        "Libellé": "Pays",
        "VM_FIN": "VM (M€)",
        "Delta_VM": "Δ VM (M€)",
        "Delta_VM_pct": "Δ VM (%)",
    })
    df_aff_geo = df_aff_geo[
        [c for c in [
            "Pays",
            "VM (M€)",
            "Δ VM (M€)",
            "Δ VM (%)",
            "Tendance",
            "Alloc (%)",
            "Δ Alloc (%)",
        ] if c in df_aff_geo.columns]
    ]

    # Base complète pour la carte
    df_geo_all = _build_concentration_table(
        dff=dff,
        d0=d0,
        d1=d1,
        group_col=geo_col,
        top_n=None,
    )

    df_geo_all = df_geo_all[df_geo_all["Libellé"] != "TOTAL"].copy()
    df_geo_all = df_geo_all[df_geo_all["VM_FIN"] > 0]

    if df_geo_all.empty:
        return df_aff_geo, None

    # --- Mapping FR -> codes ISO3 ---
    mapping_fr_to_iso3 = {
        "ALLEMAGNE": "DEU",
        "AUTRICHE": "AUT",
        "BELGIQUE": "BEL",
        "CANADA": "CAN",
        "DANEMARK": "DNK",
        "ESPAGNE": "ESP",
        "FINLANDE": "FIN",
        "FRANCE": "FRA",
        "GRÈCE": "GRC",
        "GREECE": "GRC",
        "IRLANDE": "IRL",
        "ITALIE": "ITA",
        "JAPON":"JPN",
        "LUXEMBOURG": "LUX",
        "NORVÈGE": "NOR",
        "NORVEGE": "NOR",
        "PAYS-BAS": "NLD",
        "PAYS BAS": "NLD",
        "POLOGNE": "POL",
        "PORTUGAL": "PRT",
        "SUEDE": "SWE",
        "SUÈDE": "SWE",
        "SUISSE": "CHE",
        "ROYAUME-UNI": "GBR",
        "ROYAUME UNI": "GBR",
        "UK": "GBR",
        "ETATS-UNIS": "USA",
        "ETATS UNIS": "USA",
        "ÉTATS-UNIS": "USA",
        "ÉTATS UNIS": "USA",
        "SUPRA-NATIONAL": None,
        "SUPRA NATIONAL": None,
    }

    df_geo_plot = df_geo_all.rename(columns={"Libellé": "Pays"}).copy()
    df_geo_plot["PAYS_CLEAN"] = df_geo_plot["Pays"].astype(str).str.strip().str.upper()
    df_geo_plot["PAYS_ISO_3"] = df_geo_plot["PAYS_CLEAN"].map(mapping_fr_to_iso3)

    df_countries = df_geo_plot[df_geo_plot["PAYS_ISO_3"].notna()].copy()
    df_countries = df_countries[df_countries["VM_FIN"] > 0]

    if df_countries.empty:
        return df_aff_geo, None

    # Taille des bulles
    vm_max = float(df_countries["VM_FIN"].max())
    seuil_min = vm_max * 0.0004 if vm_max else 0.0

    df_countries["VM_SIZE"] = np.where(
        df_countries["VM_FIN"] > 0.05,
        np.maximum(df_countries["VM_FIN"], seuil_min),
        0.0,
    )

    # Figure
    fig_map = px.scatter_geo(
        df_countries,
        locations="PAYS_ISO_3",
        locationmode="ISO-3",
        size="VM_SIZE",
        text="PAYS_ISO_3",
        custom_data=["Pays", "VM_FIN"],
        size_max=40,
    )

    fig_map.update_traces(
        marker=dict(color="red", opacity=0.85),
        mode="markers+text",
        textposition="middle center",
        textfont=dict(family="Arial Black", size=10, color="white", weight=700),
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "<b>VM : %{customdata[1]:,.1f} M€</b><extra></extra>"
        ),
    )

    fig_map.update_geos(
        scope=geo_scope,
        showcountries=True,
        showcoastlines=True,
        showland=True,
        landcolor="#C0C0C0",
        bgcolor="#DADADA",
    )
    fig_map.update_layout(
        margin=dict(t=0, l=0, r=0, b=0),
    )

    return df_aff_geo, fig_map

def build_risque_action_sector_section(
    dff: pd.DataFrame,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
    detail_choice: str,
):
    """
    Construit la section 'Concentration par secteur' sans Streamlit.

    Retourne :
      - df_aff_sect      : tableau complet (portefeuille)
      - fig_treemap_sect : figure treemap Plotly (ou None)
    """

    sector_candidates = ["SECTEUR_EPS", "SECTEUR_ECO", "SECTOR", "INDUSTRY", "NACE"]
    sector_col = _pick_first_existing_col(dff, sector_candidates)

    if sector_col is None:
        return None, None

    # Tableau complet via la fonction générique
    df_conc_sect = _build_concentration_table(
        dff=dff,
        d0=d0,
        d1=d1,
        group_col=sector_col,
        top_n=None,
    )

    df_aff_sect = df_conc_sect.copy()
    df_aff_sect = df_aff_sect.rename(columns={
        "Libellé": "Libellé de l'emetteur",
        "VM_FIN": "VM (M€)",
        "Delta_VM": "Δ VM (M€)",
        "Delta_VM_pct": "Δ VM (%)",
    })
    df_aff_sect = df_aff_sect[
        [c for c in [
            "Libellé de l'emetteur",
            "VM (M€)",
            "Δ VM (M€)",
            "Δ VM (%)",
            "Tendance",
            "Alloc (%)",
            "Δ Alloc (%)",
        ] if c in df_aff_sect.columns]
    ]

    # --- Treemap sur la date de fin ---
    df_treemap_base = dff[dff["DATE_TRANSPA"] == d1.date()].copy()
    df_treemap_base = df_treemap_base[df_treemap_base["VM_INIT"] > 0]

    if df_treemap_base.empty:
        return df_aff_sect, None

    sect_col = sector_col

    sous_sect_candidates = ["SOUS_SECTEUR_EPS", "SOUS_SECTEUR", "INDUSTRY_SUBGROUP"]
    sous_sect_col = _pick_first_existing_col(df_treemap_base, sous_sect_candidates)

    libelle_col = "LIBELLE" if "LIBELLE" in df_treemap_base.columns else None

    # Définition de la hiérarchie selon detail_choice
    if detail_choice == "Par secteur":
        group_cols = [sect_col]

    elif detail_choice == "Secteur → Sous-secteur" and sous_sect_col:
        group_cols = [sect_col, sous_sect_col]

    elif detail_choice == "Secteur → Sous-secteur → Titre":
        if sous_sect_col and libelle_col:
            group_cols = [sect_col, sous_sect_col, libelle_col]
        elif libelle_col:
            group_cols = [sect_col, libelle_col]
        else:
            group_cols = [sect_col]
    else:
        # fallback safe
        group_cols = [sect_col]

    # Agrégation VM (en €)
    df_treemap = (
        df_treemap_base
        .groupby(group_cols, dropna=False)["VM_INIT"]
        .sum()
        .reset_index()
    )
    df_treemap["VM_MEUR"] = df_treemap["VM_INIT"] / 1e6
    df_treemap = df_treemap[df_treemap["VM_MEUR"] > 0]

    if df_treemap.empty:
        return df_aff_sect, None

    # Nettoyage hiérarchie
    for col in group_cols:
        df_treemap[col] = df_treemap[col].fillna("n.d.").astype(str)

    fig_treemap_sect = _treemap_vm(
        df_treemap,
        path_cols=group_cols,
        value_col="VM_MEUR",
        title=None,
    )

    return df_aff_sect, fig_treemap_sect

_CSS_TABLE_HEADER = """
<style>
div[data-testid="stDataFrame"] div[role="columnheader"] {
    background-color: #714A80 !important;
    color: white !important;
    font-weight: bold !important;
}
</style>
"""

_GESTION_MAP_ACTION = {"1": "Mandats", "2": "Direct hors OPC", "3": "Fonds dédiés", "4": "Direct OPC"}
_GESTION_ORDER_ACTION = ["Mandats", "Direct hors OPC", "Fonds dédiés", "Direct OPC", "Autres"]


def _build_detail_action_table(
    dff: pd.DataFrame,
    d0,
    d1,
    filtre_sous_classe: List[str],
    filtre_pays: List[str],
    filtre_secteur: List[str],
    filtre_type_gestion: List[str],
    search_lib: str,
    top_n: int,
):
    """
    Construit le tableau détail par titre action à la date d1 avec variation d0→d1.
    Retourne (df_detail, nb_total) ou None si vide.
    """
    d0_date = pd.to_datetime(d0).date()
    d1_date = pd.to_datetime(d1).date()
    df1 = dff[dff["DATE_TRANSPA"] == d1_date].copy()
    df0 = dff[dff["DATE_TRANSPA"] == d0_date].copy()
    if df1.empty:
        return None

    # Type de gestion
    if "TYPE_GESTION_2" in df1.columns:
        df1["TYPE_GESTION_LIB"] = df1["TYPE_GESTION_2"].astype(str).map(_GESTION_MAP_ACTION).fillna("Autres")
    else:
        df1["TYPE_GESTION_LIB"] = "n.d."

    # VM numérique
    df1["VM_INIT"] = pd.to_numeric(df1["VM_INIT"], errors="coerce").fillna(0.0)
    df1 = df1[df1["VM_INIT"] > 0].copy()
    if df1.empty:
        return None

    # Colonnes optionnelles
    libelle_col  = "LIBELLE"      if "LIBELLE"      in df1.columns else None
    emetteur_col = "LIB_EMETTEUR" if "LIB_EMETTEUR" in df1.columns else None
    pays_col     = "PAYS"         if "PAYS"         in df1.columns else None
    secteur_col  = _pick_first_existing_col(df1, ["SECTEUR_EPS", "SECTEUR_ECO", "SECTOR"])
    sous_cl_col  = "SOUS_CLASSIF_RF" if "SOUS_CLASSIF_RF" in df1.columns else None

    # Pré-filtrage
    if filtre_sous_classe and sous_cl_col:
        df1 = df1[df1[sous_cl_col].isin(filtre_sous_classe)]
    if filtre_pays and pays_col:
        df1 = df1[df1[pays_col].isin(filtre_pays)]
    if filtre_secteur and secteur_col:
        df1 = df1[df1[secteur_col].isin(filtre_secteur)]
    if filtre_type_gestion:
        df1 = df1[df1["TYPE_GESTION_LIB"].isin(filtre_type_gestion)]
    if search_lib and libelle_col:
        df1 = df1[df1[libelle_col].astype(str).str.contains(search_lib, case=False, na=False)]
    if df1.empty:
        return None

    nb_total = len(df1)

    # VaR action
    for c in ["VM_PMVL_ACTION_VAR95", "VM_PMVL_ACTION_VAR99"]:
        if c in df1.columns:
            df1[c] = pd.to_numeric(df1[c], errors="coerce").fillna(df1["VM_INIT"])
        else:
            df1[c] = df1["VM_INIT"]

    df1["VAR95_MEUR"] = (df1["VM_PMVL_ACTION_VAR95"] - df1["VM_INIT"]).abs() / 1e6
    df1["VAR99_MEUR"] = (df1["VM_PMVL_ACTION_VAR99"] - df1["VM_INIT"]).abs() / 1e6
    df1["VM_FIN_MEUR"] = df1["VM_INIT"] / 1e6

    # Variation d0→d1 par titre (ID si dispo, sinon LIBELLE)
    id_col = "ID" if "ID" in df1.columns else libelle_col
    if id_col and id_col in df0.columns:
        df0["VM_INIT"] = pd.to_numeric(df0["VM_INIT"], errors="coerce").fillna(0.0)
        vm_deb = df0.groupby(id_col)["VM_INIT"].sum().rename("VM_DEBUT") / 1e6
        df1 = df1.merge(vm_deb.reset_index(), on=id_col, how="left")
        df1["VM_DEBUT"] = df1["VM_DEBUT"].fillna(0.0)
    else:
        df1["VM_DEBUT"] = 0.0

    df1["Delta_VM"]     = df1["VM_FIN_MEUR"] - df1["VM_DEBUT"]
    df1["Delta_VM_pct"] = np.where(
        df1["VM_DEBUT"] != 0,
        df1["Delta_VM"] / df1["VM_DEBUT"] * 100,
        np.nan,
    )
    df1["Tendance"] = (df1["Delta_VM_pct"] / 100).apply(trend)

    # Alloc
    total_vm = df1["VM_FIN_MEUR"].sum()
    df1["ALLOC"] = df1["VM_FIN_MEUR"] / total_vm if total_vm > 0 else 0.0

    # Tri + Top N
    df1 = df1.sort_values("VM_FIN_MEUR", ascending=False)
    if top_n > 0:
        df1 = df1.head(top_n)

    # Colonnes finales
    col_map = {}
    keep = []
    if libelle_col:
        col_map[libelle_col] = "Libellé"; keep.append(libelle_col)
    if sous_cl_col:
        col_map[sous_cl_col] = "Sous-classe d'actif"; keep.append(sous_cl_col)
    col_map["TYPE_GESTION_LIB"] = "Type de gestion"; keep.append("TYPE_GESTION_LIB")
    if emetteur_col:
        col_map[emetteur_col] = "Emetteur"; keep.append(emetteur_col)
    if pays_col:
        col_map[pays_col] = "Pays"; keep.append(pays_col)
    if secteur_col:
        col_map[secteur_col] = "Secteur"; keep.append(secteur_col)
    for c, lbl in [("VM_FIN_MEUR", "VM (M€)"), ("ALLOC", "Alloc (%)"),
                   ("Delta_VM", "Δ VM (M€)"), ("Delta_VM_pct", "Δ VM (%)"),
                   ("Tendance", "Tendance"), ("VAR95_MEUR", "VaR 95% (M€)"), ("VAR99_MEUR", "VaR 99% (M€)")]:
        col_map[c] = lbl; keep.append(c)

    result = df1[keep].rename(columns=col_map)

    # Ligne TOTAL
    t_fin   = result["VM (M€)"].sum()
    t_delta = result["Δ VM (M€)"].sum()
    t_deb   = t_fin - t_delta
    t_pct   = (t_delta / t_deb * 100) if t_deb != 0 else np.nan
    total_row = {c: "" for c in result.columns}
    first_col = result.columns[0]
    total_row[first_col]      = "TOTAL"
    total_row["VM (M€)"]      = t_fin
    total_row["Alloc (%)"]    = result["Alloc (%)"].sum()
    total_row["Δ VM (M€)"]    = t_delta
    total_row["Δ VM (%)"]     = t_pct
    total_row["Tendance"]     = trend(t_delta / t_deb if t_deb != 0 else np.nan)
    total_row["VaR 95% (M€)"] = result["VaR 95% (M€)"].sum()
    total_row["VaR 99% (M€)"] = result["VaR 99% (M€)"].sum()
    result = pd.concat([result, pd.DataFrame([total_row])], ignore_index=True)

    return result, nb_total


def _render_detail_action_section(dff: pd.DataFrame, d0, d1):
    d1_date = pd.to_datetime(d1).date()
    df_d1 = dff[dff["DATE_TRANSPA"] == d1_date].copy()
    if df_d1.empty:
        st.info("Aucune donnée disponible pour le détail par titre.")
        return

    # Type de gestion
    if "TYPE_GESTION_2" in df_d1.columns:
        df_d1["TYPE_GESTION_LIB"] = df_d1["TYPE_GESTION_2"].astype(str).map(_GESTION_MAP_ACTION).fillna("Autres")
        types_gestion_dispo = [g for g in _GESTION_ORDER_ACTION if g in df_d1["TYPE_GESTION_LIB"].unique()]
    else:
        types_gestion_dispo = []

    sous_cl_col = "SOUS_CLASSIF_RF" if "SOUS_CLASSIF_RF" in df_d1.columns else None
    pays_col    = "PAYS"            if "PAYS"            in df_d1.columns else None
    secteur_col = _pick_first_existing_col(df_d1, ["SECTEUR_EPS", "SECTEUR_ECO", "SECTOR"])

    sous_classes_dispo = sorted(df_d1[sous_cl_col].dropna().unique().tolist()) if sous_cl_col else []
    pays_dispo         = sorted(df_d1[pays_col].dropna().unique().tolist())    if pays_col    else []
    secteurs_dispo     = sorted(df_d1[secteur_col].dropna().unique().tolist()) if secteur_col else []

    # Ligne 1 de filtres
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        filtre_sous_classe = st.multiselect("Sous-classe d'actif", options=sous_classes_dispo, default=[], key="det_action_sc")
    with fc2:
        filtre_pays = st.multiselect("Pays", options=pays_dispo, default=[], key="det_action_pays")
    with fc3:
        filtre_secteur = st.multiselect("Secteur", options=secteurs_dispo, default=[], key="det_action_secteur")
    with fc4:
        filtre_type_gestion = st.multiselect("Type de gestion", options=types_gestion_dispo, default=[], key="det_action_gestion")

    # Ligne 2 de filtres
    fc5, fc6 = st.columns([3, 1])
    with fc5:
        search_lib = st.text_input("Libellé (recherche)", value="", key="det_action_lib")
    with fc6:
        top_n = st.selectbox(
            "Top N titres",
            options=[20, 50, 100, 0],
            format_func=lambda x: "Tous" if x == 0 else str(x),
            index=1,
            key="det_action_topn",
        )

    result = _build_detail_action_table(
        dff, d0, d1,
        filtre_sous_classe, filtre_pays, filtre_secteur,
        filtre_type_gestion, search_lib, top_n,
    )

    if result is None:
        st.info("Aucun titre ne correspond aux filtres sélectionnés.")
        return

    df_detail, nb_total = result
    nb_affiches = len(df_detail) - 1  # hors ligne TOTAL

    st.caption(
        f"{nb_affiches} titre(s) affiché(s)"
        + (f" sur {nb_total}" if top_n > 0 and nb_affiches < nb_total else "")
    )

    styled = apply_common_table_styles(
        df_detail,
        total_cols=(df_detail.columns[0],),
        delta_meur_col="Δ VM (M€)",
        delta_pct_col="Δ VM (%)",
        tendance_col="Tendance",
    )
    render_static_dataframe(styled)

    excel_bytes = df_to_excel_bytes(df_detail, sheet_name="Risque_Action_Titres")
    st.download_button(
        label="📥 Télécharger en Excel",
        data=excel_bytes,
        file_name="risque_action_detail_titres.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="det_action_excel",
    )


def render_risque_action_tab(df_selection: pd.DataFrame, date_debut, date_fin):
    st.markdown(_CSS_TABLE_HEADER, unsafe_allow_html=True)
    st.subheader("Risque Action")

    # Préparation base
    prep = _prepare_action_base(df_selection, date_debut, date_fin)
    if prep is None:
        st.info("Aucune donnée disponible pour le Risque Action sur la période sélectionnée.")
        return

    dff, d0, d1 = prep
    
    # ------------------------------------------------------
    # Choix dimension d'analyse 
    # ------------------------------------------------------
    
    st.markdown(
        f"Période : **{d0.strftime('%d-%m-%Y')}** ⮕ "
        f"**{d1.strftime('%d-%m-%Y')}**"
    )

    # ======================================================
    # 1) Concentration par émetteur / groupe
    # ======================================================
    st.markdown("### Risque de concentration par émetteur / groupe")
    
    # Le radio ne s'applique qu'à cette section
    choix_dim_affichage = st.radio(
        "Vue par :",
        options=["Type de groupe", "Type d'émetteur"],
        index=0,
        horizontal=True,
        key="risque_action_vue_par",  # clé locale à la section
    )

    # On délègue le calcul + la figure à la fonction réutilisable
    label_header, df_aff, fig_treemap = build_risque_action_issuer_section(
        dff=dff,
        d0=d0,
        d1=d1,
        choix_dim_affichage=choix_dim_affichage,
    )

    if label_header is None:
        # Pas de colonne de groupe / émetteur trouvée
        st.info(
            "Impossible de calculer la concentration par émetteur / groupe.\n\n"
            "Colonnes candidates : "
            + (", ".join(["LIB_GROUPE", "GROUPE", "EMETTEUR_GROUPE",
                          "LIB_EMETTEUR", "EMETTEUR", "NOM_EMETTEUR"]))
        )
    else:
        st.markdown("**Top 10 émetteur / groupe**")
        col_tab, col_heat = st.columns([1.5, 1])

        with col_tab:
            render_static_dataframe(apply_common_table_styles(df_aff))

            excel_bytes = df_to_excel_bytes(df_aff, sheet_name="Top10_Emetteur_Groupe")
            st.download_button(
                label="📥Télécharger en Excel",
                data=excel_bytes,
                file_name="risque_action_top10_emetteur_groupe.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with col_heat:
            if fig_treemap is None:
                st.info("Treemap indisponible : aucune exposition positive.")
            else:
                st.plotly_chart(fig_treemap, use_container_width=True, config={"displayModeBar": "hover"})

    st.markdown("---")

    # ======================================================
    # 2) Concentration géographique
    # ======================================================
    st.markdown("### Risque de concentration géographique")

    # Choix de la vue carte (UI seulement)
    scope_options = {
        "Europe (défaut)": "europe",
        "Monde": "world",
        "Amérique du Nord": "north america",
        "Amérique du Sud": "south america",
        "Asie": "asia",
        "Afrique": "africa",
    }
    scope_label = st.radio(
        "Vue carte :",
        options=list(scope_options.keys()),
        index=0,
        horizontal=True,
        key="risque_action_scope_geo",
    )
    geo_scope = scope_options[scope_label]

    # On délègue les calculs + figure à la fonction réutilisable
    df_aff_geo, fig_map = build_risque_action_geo_section(
        dff=dff,
        d0=d0,
        d1=d1,
        geo_scope=geo_scope,
    )

    if df_aff_geo is None:
        st.info(
            "Impossible de calculer la concentration géographique.\n\n"
            "Colonnes candidates : "
            "PAYS, PAYS_EMETTEUR, COUNTRY, COUNTRY_OF_RISK, ZONE, ZONE_ACTION"
        )
    else:
        st.markdown("**Top 10 géographique**")
        col_tab, col_map = st.columns([1.5, 1])

        with col_tab:
            render_static_dataframe(apply_common_table_styles(df_aff_geo))

            excel_bytes = df_to_excel_bytes(df_aff_geo, sheet_name="Top10_Geographie")
            st.download_button(
                label="📥Télécharger en Excel",
                data=excel_bytes,
                file_name="risque_action_top10_geographique.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with col_map:
            if fig_map is None:
                st.info("Carte indisponible : aucune exposition positive ou aucun pays mappé.")
            else:
                st.plotly_chart(fig_map, use_container_width=True, config={"displayModeBar": "hover"})
    st.markdown("---")

    # ======================================================
    # 3) Concentration secteur (tableau complet + treemap)
    # ======================================================
    st.markdown("### Risque de concentration par secteur")

    # UI : choix du niveau de détail
    detail_choice = st.radio(
        "Niveau de détail :",
        options=[
            "Par secteur",
            "Secteur → Sous-secteur",
            "Secteur → Sous-secteur → Titre",
        ],
        index=0,
        horizontal=False,
        key="risque_action_treemap_secteur_detail",
    )

    # On délègue calcul + figure à la fonction réutilisable
    df_aff_sect, fig_treemap_sect = build_risque_action_sector_section(
        dff=dff,
        d0=d0,
        d1=d1,
        detail_choice=detail_choice,
    )

    if df_aff_sect is None:
        st.info(
            "Impossible de calculer la concentration par secteur.\n\n"
            "Colonnes candidates : SECTEUR_EPS, SECTEUR_ECO, SECTOR, INDUSTRY, NACE"
        )
        st.session_state["rapport_action"] = {
            "fig_issuer":    fig_treemap if label_header is not None else None,
            "fig_geo":       fig_map if df_aff_geo is not None else None,
            "fig_secteur":   None,
            "table_issuer":  df_aff if label_header is not None else None,
            "table_geo":     df_aff_geo,
            "table_secteur": None,
        }
        return

    st.markdown("**Concentration par secteur (portefeuille complet)**")
    col_tab, col_heat = st.columns([1.5, 1])

    with col_tab:
        render_static_dataframe(apply_common_table_styles(df_aff_sect))

        excel_bytes = df_to_excel_bytes(df_aff_sect, sheet_name="Concentration_Secteur")
        st.download_button(
            label="📥Télécharger en Excel",
            data=excel_bytes,
            file_name="risque_action_concentration_secteur.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_heat:
        if fig_treemap_sect is None:
            st.info("Treemap indisponible : aucune exposition positive après agrégation.")
        else:
            st.plotly_chart(fig_treemap_sect, use_container_width=True, config={"displayModeBar": "hover"})

    # Stockage pour l'onglet Rapport
    st.session_state["rapport_action"] = {
        "fig_issuer":    fig_treemap if label_header is not None else None,
        "fig_geo":       fig_map if df_aff_geo is not None else None,
        "fig_secteur":   fig_treemap_sect,
        "table_issuer":  df_aff if label_header is not None else None,
        "table_geo":     df_aff_geo,
        "table_secteur": df_aff_sect,
    }

    # ======================================================
    # Détail par titre
    # ======================================================
    st.markdown("---")
    show_detail = st.toggle("Afficher le détail par titre", value=False, key="action_detail_toggle")
    if show_detail:
        _render_detail_action_section(dff, d0, d1)