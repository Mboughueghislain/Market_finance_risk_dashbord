# dashboard/modules/risque_taux.py

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from typing import Tuple, List, Optional

from modules.risque_action import _pick_first_existing_col
from modules.format_utils import (
    fmt_meur,
    df_to_excel_bytes,
    apply_common_table_styles,
    render_static_dataframe,
    add_alloc_columns,
)

# ==========================================================
# Constantes & mappings
# ==========================================================

#Nom de la colonne Duration
DURATION_LABEL_COL = "Duration"
# Type de gestion (code -> libellé)
MAPPING_GESTION = {
    "1": "Mandats",
    "2": "Direct hors OPC",
    "3": "Fonds dédiés",
    "4": "Direct OPC",
}

# Ordre logique des types de gestion
GESTION_ORDER = ["Mandats", "Direct hors OPC", "Fonds dédiés", "Direct OPC", "Autres"]

# Couleurs des types de gestion
GESTION_COLORS = {
    "Mandats": "#714A80",
    "Direct hors OPC": "#ec2525",
    "Fonds dédiés": "#2ca02c",
    "Direct OPC": "#ff7f0e",
    "Autres": "#7f7f7f",
}

# Couleurs pour Var / VaR
VAR_MEASURES_ORDER = ["Δ VM (M€)", "VaR 95% (M€)", "VaR 99% (M€)"]
VAR_COLORS = {
    "Δ VM (M€)": "#181717",  
    "VaR 95% (M€)": "#714A80",          
    "VaR 99% (M€)": "#ec2525",           
}


# ==========================================================
# Helpers
# ==========================================================

def _prepare_taux_base(
    df_selection: pd.DataFrame,
    date_debut,
    date_fin,
    risk_col: str = "RSQ_FIN_TAUX",
) -> Optional[Tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, str]]:
    """
    Filtre la base sur RSQ_FIN_TAUX == 1, choisit la colonne de duration,
    calcule les dates d0 / d1.
    Retourne (dff, d0, d1, dim_col) ou None si problème.
    """
    if risk_col not in df_selection.columns:
        st.info(f"Colonne **{risk_col}** absente, impossible de calculer le risque taux.")
        return None

    # Colonne de dimension (duration)
    duration_candidates = ["SEGMENT_DURATION", "DURATION"]
    dim_col = _pick_first_existing_col(df_selection, duration_candidates)
    if dim_col is None:
        st.info(
            "Impossible de trouver une colonne de duration parmi "
            f"{duration_candidates}."
        )
        return None

    dff = df_selection.copy()
    dff = dff[dff[risk_col].astype(str) == "1"].copy()
    if dff.empty:
        st.info("Aucune ligne marquée RSQ_FIN_TAUX = 1 avec les filtres actuels.")
        return None

    dff[dim_col] = dff[dim_col].fillna("n.d.")

    if "DATE_TRANSPA" not in dff.columns:
        st.info("Colonne DATE_TRANSPA absente, impossible de calculer les variations.")
        return None

    dff["DATE_TRANSPA"] = pd.to_datetime(dff["DATE_TRANSPA"]).dt.date
    d0 = dff.loc[dff["DATE_TRANSPA"] <= pd.to_datetime(date_debut).date(), "DATE_TRANSPA"].max()
    d1 = dff.loc[dff["DATE_TRANSPA"] <= pd.to_datetime(date_fin).date(), "DATE_TRANSPA"].max()

    if pd.isna(d0) or pd.isna(d1):
        st.info("Aucune date de transparisation valide pour la période sélectionnée.")
        return None

    return dff, pd.to_datetime(d0), pd.to_datetime(d1), dim_col


def _build_table_duration_gestion(
    dff: pd.DataFrame,
    dim_col: str,
    d1: pd.Timestamp,
) -> Optional[Tuple[pd.DataFrame, pd.DataFrame, List[str], List[str]]]:
    """
    Construit le tableau 'Excel-like' Duration x Type de gestion.
    - dff : base filtrée Taux
    - dim_col : colonne de duration
    - d1 : date de fin

    Retourne :
      - view_table : tableau formaté (Duration, Mandats, ..., Total) en M€
      - pivot_meur : pivot sans colonne Duration, index = SEGMENT_DURATION, valeurs en M€
      - cols_gestion : liste des colonnes de gestion présentes
      - order_duration : liste ordonnée des labels de duration
    """
    df_conc = dff[dff["DATE_TRANSPA"] == d1.date()].copy()
    if df_conc.empty:
        st.info("Aucune donnée disponible pour construire le tableau de duration.")
        return None

    # Colonne SEGMENT_DURATION propre
    if "SEGMENT_DURATION" in df_conc.columns:
        df_conc["SEGMENT_DURATION"] = df_conc["SEGMENT_DURATION"].fillna("n.d.")
    else:
        df_conc["SEGMENT_DURATION"] = df_conc[dim_col].fillna("n.d.")

    # Mapping type de gestion
    if "TYPE_GESTION_2" in df_conc.columns:
        df_conc["TYPE_GESTION_2"] = df_conc["TYPE_GESTION_2"].astype(str)
    else:
        df_conc["TYPE_GESTION_2"] = "Autres"

    df_conc["TYPE_GESTION_LIB"] = (
        df_conc["TYPE_GESTION_2"].map(MAPPING_GESTION).fillna("Autres")
    )

    # VM_INIT propre
    df_conc["VM_INIT"] = pd.to_numeric(df_conc["VM_INIT"], errors="coerce").fillna(0.0)
    df_conc = df_conc[df_conc["VM_INIT"] > 0]
    if df_conc.empty:
        st.info("Pas de VM positive pour construire le tableau de duration.")
        return None

    # Ordre des durations via NUM_SEGMENT si dispo
    if "NUM_SEGMENT" in df_conc.columns:
        df_conc["NUM_SEGMENT"] = pd.to_numeric(df_conc["NUM_SEGMENT"], errors="coerce")
        order_duration = (
            df_conc.groupby("SEGMENT_DURATION")["NUM_SEGMENT"]
            .min()
            .sort_values()
            .index
            .tolist()
        )
    else:
        order_duration = sorted(df_conc["SEGMENT_DURATION"].unique())

    # Pivot duration x type de gestion (en €)
    pivot = pd.pivot_table(
        df_conc,
        index="SEGMENT_DURATION",
        columns="TYPE_GESTION_LIB",
        values="VM_INIT",
        aggfunc="sum",
        fill_value=0.0,
    )

    # Colonnes de gestion présentes
    cols_gestion = [c for c in GESTION_ORDER if c in pivot.columns]
    pivot = pivot[cols_gestion]
    pivot = pivot.reindex(order_duration)

    # Passage en M€
    pivot_meur = pivot / 1e6

    # Vue pour le tableau final
    view_table = pivot_meur.reset_index().rename(
        columns={"SEGMENT_DURATION": "Duration"}
    )
    view_table["Total"] = view_table[cols_gestion].sum(axis=1)

    # Ligne TOTAL
    total_values = {"Duration": "TOTAL"}
    for c in cols_gestion + ["Total"]:
        total_values[c] = view_table[c].sum()
    view_table = pd.concat([view_table, pd.DataFrame([total_values])], ignore_index=True)

    return view_table, pivot_meur, cols_gestion, order_duration


def _style_table_with_total(view_table: pd.DataFrame, cols_gestion: List[str]):
    """
    Applique :
      - format M€ sur les colonnes de gestion + Total
      - style violet sur la ligne TOTAL (via style_total_row déjà importée)
      - style violet sur la colonne Total
    """
    # mapping de format pour les colonnes de gestion + Total
    fmt_map = {c: fmt_meur for c in (cols_gestion + ["Total"]) if c in view_table.columns}
    
    #application du format et des styles(TOTAL violet + colonne Total etc)
    styled = apply_common_table_styles(
        view_table,
        fmt_map=fmt_map,
        # ici on dit à la fonction comment identifier la ligne TOTAL et la colonne Total pour appliquer les styles spécifiques
        total_cols=("Duration",),   # Car total est dans Duration
    )
    return styled


def _build_var_stress_table(
    dff: pd.DataFrame,
    dim_col: str,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
    order_duration: List[str],
) -> pd.DataFrame:
    """
    Construit le tableau Variation par période / VaR 95 / VaR 99 par duration (en M€) + ligne TOTAL.
    Retourne df_var_view (Duration, Var période, VaR95, VaR99).
    """
    # --- Variation par période (Δ VM) ---
    df0 = dff[dff["DATE_TRANSPA"] == d0.date()].copy()
    df1 = dff[dff["DATE_TRANSPA"] == d1.date()].copy()

    for sub in (df0, df1):
        sub["VM_INIT"] = pd.to_numeric(sub["VM_INIT"], errors="coerce").fillna(0.0)

    debut = (
        df0.groupby(dim_col, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_DEBUT")
    )
    fin = (
        df1.groupby(dim_col, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_FIN")
    )

    res = (
        pd.concat([debut, fin], axis=1)
        .fillna(0.0)
        .reset_index()
    )
    res["Delta_VM"] = res["VM_FIN"] - res["VM_DEBUT"]

    # --- Stress : VM_REF, VM_VAR95, VM_VAR99 ---
    df_end = df1.copy()
    stress_cols = ["VM_INIT", "VM_PMVL_TAUX_VAR95", "VM_PMVL_TAUX_VAR99"]
    for c in stress_cols:
        df_end[c] = pd.to_numeric(df_end[c], errors="coerce").fillna(0.0)

    agg_stress = (
        df_end
        .groupby(dim_col, dropna=False)[stress_cols]
        .sum()
        .rename(columns={
            "VM_INIT": "VM_REF",
            "VM_PMVL_TAUX_VAR95": "VM_VAR95",
            "VM_PMVL_TAUX_VAR99": "VM_VAR99",
        })
        .reset_index()
    )

    df_var = agg_stress.merge(res[[dim_col, "Delta_VM"]], on=dim_col, how="left")

    df_var["VAR_PERIODE"] = df_var["Delta_VM"]
    df_var["VAR95"] = (df_var["VM_VAR95"] - df_var["VM_REF"]).abs()
    df_var["VAR99"] = (df_var["VM_VAR99"] - df_var["VM_REF"]).abs()

    df_var_view = df_var[[dim_col, "VAR_PERIODE", "VAR95", "VAR99"]].copy()
    df_var_view["VAR_PERIODE"] /= 1e6
    df_var_view["VAR95"] /= 1e6
    df_var_view["VAR99"] /= 1e6

    df_var_view = df_var_view.rename(columns={
        dim_col: "Duration",
        "VAR_PERIODE": "Δ VM (M€)",
        "VAR95": "VaR 95% (M€)",
        "VAR99": "VaR 99% (M€)",
    })

    # Tri des durations
    df_var_view["Duration"] = pd.Categorical(
        df_var_view["Duration"],
        categories=order_duration,
        ordered=True,
    )
    df_var_view = df_var_view.sort_values("Duration")

    # Ligne TOTAL
    total_row = pd.DataFrame([{
        "Duration": "TOTAL",
        "Δ VM (M€)": df_var_view["Δ VM (M€)"].sum(),
        "VaR 95% (M€)": df_var_view["VaR 95% (M€)"].sum(),
        "VaR 99% (M€)": df_var_view["VaR 99% (M€)"].sum(),
    }])
    df_var_view = pd.concat([df_var_view, total_row], ignore_index=True)

    return df_var_view


def build_taux_duration_block(
    dff: pd.DataFrame,
    dim_col: str,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
):
    """
    Construit le bloc 'Duration x Type de gestion' SANS Streamlit.
    Retourne un dict avec :
      - d0, d1
      - view_table           : tableau M€ + Total
      - pivot_meur           : pivot brut (index = SEGMENT_DURATION)
      - cols_gestion         : liste des colonnes de gestion
      - order_duration       : ordre des durations
      - fig_stack, fig_total : figures Plotly (graph segmenté + cumulé)
    """

    table_build = _build_table_duration_gestion(dff, dim_col, d1)
    if table_build is None:
        return None

    view_table, pivot_meur, cols_gestion, order_duration = table_build

    # Graph 1 : empilé par segment de duration
    df_stack = (
        pivot_meur[cols_gestion]
        .reset_index()
        .melt(
            id_vars="SEGMENT_DURATION",
            value_vars=cols_gestion,
            var_name="Type de gestion",
            value_name="VM_MEUR",
        )
    )
    df_stack["TOTAL_MEUR"] = df_stack.groupby("SEGMENT_DURATION")["VM_MEUR"].transform("sum")

    fig_stack = px.bar(
        df_stack,
        x="SEGMENT_DURATION",
        y="VM_MEUR",
        color="Type de gestion",
        barmode="stack",
        labels={
            "SEGMENT_DURATION": "Duration",
            "VM_MEUR": "VM (M€)",
            "Type de gestion": "Type de gestion",
        },
        custom_data=["VM_MEUR", "TOTAL_MEUR", "Type de gestion"],
        color_discrete_map=GESTION_COLORS,
    )
    fig_stack.update_layout(margin=dict(t=0, b=40, l=40, r=10))
    fig_stack.update_traces(
        hovertemplate=(
            "<b>Type de gestion : %{customdata[2]}</b><br>"
            "<b>Duration : %{x}</b><br>"
            "<b>VM segment : %{customdata[0]:,.1f} M€</b><br>"
            "<b>Total duration : %{customdata[1]:,.1f} M€</b><br>"
            "<extra></extra>"
        )
    )

    # Graph 2 : cumulé
    totals_par_gestion = pivot_meur[cols_gestion].sum(axis=0)
    df_total_long = pd.DataFrame({
        "Duration": ["Total"] * len(cols_gestion),
        "Type de gestion": totals_par_gestion.index,
        "VM_MEUR": totals_par_gestion.values,
    })
    total_global = totals_par_gestion.sum()
    df_total_long["TOTAL_MEUR"] = total_global
    df_total_long["PCT_TOTAL"] = df_total_long["VM_MEUR"] / df_total_long["TOTAL_MEUR"]

    fig_total = px.bar(
        df_total_long,
        x=DURATION_LABEL_COL,
        y="VM_MEUR",
        color="Type de gestion",
        barmode="stack",
        labels={
            DURATION_LABEL_COL: "",
            "VM_MEUR": "VM (M€)",
            "Type de gestion": "Type de gestion",
        },
        custom_data=["VM_MEUR", "TOTAL_MEUR", "PCT_TOTAL", "Type de gestion"],
        color_discrete_map=GESTION_COLORS,
    )
    fig_total.update_layout(margin=dict(t=0, b=40, l=40, r=10))
    fig_total.update_traces(
        hovertemplate=(
            "<b>Type de gestion : %{customdata[3]}</b><br>"
            "<b>VM : %{customdata[0]:,.1f} M€</b><br>"
            "<b>Total VM : %{customdata[1]:,.1f} M€</b><br>"
            "<b>Poids dans le total : %{customdata[2]:.1%}</b><br>"
            "<extra></extra>"
        )
    )

    return {
        "d0": d0,
        "d1": d1,
        "view_table": view_table,
        "pivot_meur": pivot_meur,
        "cols_gestion": cols_gestion,
        "order_duration": order_duration,
        "fig_stack": fig_stack,
        "fig_total": fig_total,
    }
    
def build_taux_var_block(
    dff: pd.DataFrame,
    dim_col: str,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
    order_duration: List[str],
):
    """
    Construit le bloc 'Var période & Stress (VaR)' SANS Streamlit.
    Retourne un dict avec :
      - df_var_view    : tableau complet (inclut TOTAL)
      - fig_var_seg    : barres groupées par duration
      - fig_var_tot    : barres groupées cumulées
    """

    df_var_view = _build_var_stress_table(dff, dim_col, d0, d1, order_duration)

    # On enlève TOTAL pour les graphes
    df_plot = df_var_view[df_var_view[DURATION_LABEL_COL] != "TOTAL"].copy()

    df_plot_long = df_plot.melt(
        id_vars=DURATION_LABEL_COL,
        value_vars=VAR_MEASURES_ORDER,
        var_name="Mesure",
        value_name="Valeur_MEUR",
    )

    # Graphique 1 : barres groupées par Duration
    fig_var_seg = px.bar(
        df_plot_long,
        x=DURATION_LABEL_COL,
        y="Valeur_MEUR",
        color="Mesure",
        barmode="group",
        category_orders={"Mesure": VAR_MEASURES_ORDER},
        labels={
            DURATION_LABEL_COL: "Duration",
            "Valeur_MEUR": "Millions",
            "Mesure": "",
        },
        color_discrete_map=VAR_COLORS,
        custom_data=["Valeur_MEUR", "Mesure"],
    )
    fig_var_seg.update_layout(margin=dict(t=0, b=40, l=40, r=10))
    fig_var_seg.update_traces(
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>"
            "<b>Duration : %{x}</b><br>"
            "<b>Valeur : %{customdata[0]:,.1f} M€</b><br>"
            "<extra></extra>"
        )
    )

    # Graphique 2 : cumulés
    totals = (
        df_plot_long
        .groupby("Mesure", as_index=False)["Valeur_MEUR"]
        .sum()
    )
    totals[DURATION_LABEL_COL] = "Total"

    fig_var_tot = px.bar(
        totals,
        x=DURATION_LABEL_COL,
        y="Valeur_MEUR",
        color="Mesure",
        barmode="group",
        category_orders={"Mesure": VAR_MEASURES_ORDER},
        labels={
            DURATION_LABEL_COL: "",
            "Valeur_MEUR": "Millions",
            "Mesure": "",
        },
        color_discrete_map=VAR_COLORS,
        custom_data=["Valeur_MEUR", "Mesure"],
    )
    fig_var_tot.update_layout(margin=dict(t=0, b=40, l=40, r=10))
    fig_var_tot.update_traces(
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>"
            "<b>Valeur : %{customdata[0]:,.1f} M€</b><br>"
            "<extra></extra>"
        )
    )

    return {
        "df_var_view": df_var_view,
        "fig_var_seg": fig_var_seg,
        "fig_var_tot": fig_var_tot,
    }

# ==========================================================
# Détail par titre
# ==========================================================

def _build_detail_titres_table(
    dff: pd.DataFrame,
    d0: pd.Timestamp,
    d1: pd.Timestamp,
    filtre_sous_classe: List[str],
    filtre_type_gestion: List[str],
    filtre_duration: List[str],
    search_lib: str,
    search_id: str,
    top_n: int,
    sort_asc: bool = False,
) -> Optional[Tuple["pd.DataFrame", int]]:
    """
    Construit le tableau détail par titre (d1), avec Alloc à d0 et d1.
    Retourne (df_detail, nb_total_avant_top) ou None si vide.
    """
    df1 = dff[dff["DATE_TRANSPA"] == d1.date()].copy()
    df0 = dff[dff["DATE_TRANSPA"] == d0.date()].copy()
    if df1.empty:
        return None

    id_col = "ID" if "ID" in df1.columns else None

    for sub in (df1, df0):
        sub["TYPE_GESTION_2"]  = sub["TYPE_GESTION_2"].astype(str)
        sub["TYPE_GESTION_LIB"] = sub["TYPE_GESTION_2"].map(MAPPING_GESTION).fillna("Autres")
        sub["VM_INIT"] = pd.to_numeric(sub["VM_INIT"], errors="coerce").fillna(0.0)

    df1 = df1[df1["VM_INIT"] > 0].copy()
    if df1.empty:
        return None

    if filtre_sous_classe:
        df1 = df1[df1["SOUS_CLASSIF_RF"].isin(filtre_sous_classe)]
    if filtre_type_gestion:
        df1 = df1[df1["TYPE_GESTION_LIB"].isin(filtre_type_gestion)]
    if filtre_duration:
        df1 = df1[df1["SEGMENT_DURATION"].isin(filtre_duration)]
    if df1.empty:
        return None

    for c in ["VM_PMVL_TAUX_VAR95", "VM_PMVL_TAUX_VAR99"]:
        df1[c] = pd.to_numeric(df1[c], errors="coerce").fillna(df1["VM_INIT"])
    df1["VM_MEUR"]    = df1["VM_INIT"] / 1e6
    df1["VAR95_MEUR"] = (df1["VM_PMVL_TAUX_VAR95"] - df1["VM_INIT"]).abs() / 1e6
    df1["VAR99_MEUR"] = (df1["VM_PMVL_TAUX_VAR99"] - df1["VM_INIT"]).abs() / 1e6

    # Colonnes de regroupement — mêmes pour d0 et d1 pour cohérence du Delta_VM
    grp_cols = (["ID"] if id_col else []) + ["LIBELLE"]
    for c in ["SOUS_CLASSIF_RF", "TYPE_GESTION_LIB", "SEGMENT_DURATION"]:
        if c in df1.columns:
            grp_cols.append(c)

    # Agrégation d1
    agg = (
        df1.groupby(grp_cols, dropna=False)[["VM_MEUR", "VAR95_MEUR", "VAR99_MEUR"]]
        .sum()
        .reset_index()
    )

    # Agrégation d0 sur les mêmes colonnes → VM_DEBUT cohérent
    d0_grp = [c for c in grp_cols if c in df0.columns]
    if not df0.empty and d0_grp:
        vm_debut = (
            df0.groupby(d0_grp, dropna=False)["VM_INIT"]
            .sum()
            .rename("VM_DEBUT")
            / 1e6
        ).reset_index()
        agg = agg.merge(vm_debut, on=d0_grp, how="left")
    agg["VM_DEBUT"] = agg["VM_DEBUT"].fillna(0.0) if "VM_DEBUT" in agg.columns else 0.0

    agg["Delta_VM"] = agg["VM_MEUR"] - agg["VM_DEBUT"]
    agg["Delta_VM_pct"] = np.where(
        agg["VM_DEBUT"] != 0,
        agg["Delta_VM"] / agg["VM_DEBUT"] * 100,
        np.nan,
    )

    # Positions liquidées : présentes en d0 mais absentes de agg à d1
    vm_liquidee = 0.0
    if not df0.empty and d0_grp:
        df0_filt = df0.copy()
        if filtre_sous_classe:
            df0_filt = df0_filt[df0_filt["SOUS_CLASSIF_RF"].isin(filtre_sous_classe)] if "SOUS_CLASSIF_RF" in df0_filt.columns else df0_filt
        if filtre_type_gestion:
            df0_filt = df0_filt[df0_filt["TYPE_GESTION_LIB"].isin(filtre_type_gestion)] if "TYPE_GESTION_LIB" in df0_filt.columns else df0_filt
        if filtre_duration:
            df0_filt = df0_filt[df0_filt["SEGMENT_DURATION"].isin(filtre_duration)] if "SEGMENT_DURATION" in df0_filt.columns else df0_filt
        d0_all = (
            df0_filt.groupby(d0_grp, dropna=False)["VM_INIT"]
            .sum()
            .reset_index()
            .rename(columns={"VM_INIT": "_VM_D0"})
        )
        d1_keys = agg[d0_grp].drop_duplicates()
        sold = d0_all.merge(d1_keys, on=d0_grp, how="left", indicator=True)
        sold = sold[sold["_merge"] == "left_only"]
        vm_liquidee = float(sold["_VM_D0"].sum()) / 1e6

    # Totaux sur la totalité de agg (avant filtre texte) pour la ligne TOTAL
    total_vm_all    = float(agg["VM_MEUR"].sum())
    total_delta_all = float(agg["Delta_VM"].sum()) - vm_liquidee
    total_var95_all = float(agg["VAR95_MEUR"].sum())
    total_var99_all = float(agg["VAR99_MEUR"].sum())

    # Filtre ID (après agrégation)
    if search_lib:
        agg = agg[agg["LIBELLE"].astype(str).str.contains(search_lib, case=False, na=False)]
    if search_id and id_col:
        agg = agg[agg["ID"].astype(str).str.contains(search_id, case=False, na=False)]
    if agg.empty:
        return None

    nb_total = len(agg)

    # Tri par VM décroissante, puis séparation top_n / autres
    agg = agg.sort_values("VM_MEUR", ascending=sort_asc)
    if top_n > 0:
        df_top    = agg.head(top_n).copy()
        df_autres = agg.iloc[top_n:].copy()
    else:
        df_top    = agg.copy()
        df_autres = pd.DataFrame()

    cols = (["ID"] if id_col else []) + [
        "LIBELLE", "SOUS_CLASSIF_RF", "TYPE_GESTION_LIB", "SEGMENT_DURATION",
        "VM_MEUR", "VM_DEBUT", "Delta_VM", "Delta_VM_pct", "VAR95_MEUR", "VAR99_MEUR",
    ]
    result = df_top[[c for c in cols if c in df_top.columns]].copy()

    # Ligne "Autres" — agrège toutes les lignes hors top N
    if not df_autres.empty:
        a_delta = df_autres["Delta_VM"].sum()
        a_deb   = df_autres["VM_DEBUT"].sum()
        autres_row = {
            "LIBELLE":          "Autres",
            "SOUS_CLASSIF_RF":  "",
            "TYPE_GESTION_LIB": "",
            "SEGMENT_DURATION": "",
            "VM_MEUR":          df_autres["VM_MEUR"].sum(),
            "VM_DEBUT":         a_deb,
            "Delta_VM":         a_delta,
            "Delta_VM_pct":     (a_delta / a_deb * 100) if a_deb != 0 else np.nan,
            "VAR95_MEUR":       df_autres["VAR95_MEUR"].sum(),
            "VAR99_MEUR":       df_autres["VAR99_MEUR"].sum(),
        }
        if id_col:
            autres_row["ID"] = ""
        result = pd.concat([result, pd.DataFrame([autres_row])], ignore_index=True)

    # Alloc (%) et Δ Alloc (%) — basés sur VM_total à d0 et d1 (top + autres = 100 %)
    result = add_alloc_columns(result, vm_fin_col="VM_MEUR", delta_vm_col="Delta_VM")
    result = result.drop(columns=["VM_DEBUT"])

    rename_map = {
        "LIBELLE":          "Libellé",
        "SOUS_CLASSIF_RF":  "Sous-classe d'actif",
        "TYPE_GESTION_LIB": "Type de gestion",
        "SEGMENT_DURATION": "Duration",
        "VM_MEUR":          "VM (M€)",
        "Delta_VM":         "Δ VM (M€)",
        "Delta_VM_pct":     "Δ VM (%)",
        "VAR95_MEUR":       "VaR 95% (M€)",
        "VAR99_MEUR":       "VaR 99% (M€)",
    }
    result = result.rename(columns=rename_map)

    # Ligne Positions liquidées
    if vm_liquidee > 0:
        liq_row = {c: "" for c in result.columns}
        liq_row["Libellé"]      = "Positions liquidées"
        liq_row["VM (M€)"]      = 0.0
        liq_row["Δ VM (M€)"]    = -vm_liquidee
        liq_row["Δ VM (%)"]     = -100.0
        liq_row["VaR 95% (M€)"] = 0.0
        liq_row["VaR 99% (M€)"] = 0.0
        result = pd.concat([result, pd.DataFrame([liq_row])], ignore_index=True)

    # Ligne TOTAL (inclut les positions liquidées)
    t_deb = total_vm_all - total_delta_all
    total_row = {c: "" for c in result.columns}
    total_row["Libellé"]      = "TOTAL"
    total_row["VM (M€)"]      = total_vm_all
    total_row["Δ VM (M€)"]    = total_delta_all
    total_row["Δ VM (%)"]     = (total_delta_all / t_deb * 100) if t_deb != 0 else np.nan
    total_row["Alloc (%)"]    = 100.0
    total_row["Δ Alloc (%)"]  = 0.0
    total_row["VaR 95% (M€)"] = total_var95_all
    total_row["VaR 99% (M€)"] = total_var99_all
    result = pd.concat([result, pd.DataFrame([total_row])], ignore_index=True)

    return result, nb_total


def _render_detail_titres_section(dff: pd.DataFrame, d0: pd.Timestamp, d1: pd.Timestamp):
    """
    Affiche les filtres locaux + tableau détail par titre pour le risque taux.
    """
    df_d1 = dff[dff["DATE_TRANSPA"] == d1.date()].copy()
    if df_d1.empty:
        st.info("Aucune donnée disponible pour le détail par titre.")
        return

    # Mapping gestion pour peupler les filtres
    df_d1["TYPE_GESTION_2"] = df_d1["TYPE_GESTION_2"].astype(str)
    df_d1["TYPE_GESTION_LIB"] = df_d1["TYPE_GESTION_2"].map(MAPPING_GESTION).fillna("Autres")

    # Valeurs disponibles pour les filtres
    sous_classes_dispo = sorted(df_d1["SOUS_CLASSIF_RF"].dropna().unique().tolist())
    type_gestion_dispo  = [g for g in GESTION_ORDER if g in df_d1["TYPE_GESTION_LIB"].unique()]
    durations_dispo     = []
    if "NUM_SEGMENT" in df_d1.columns:
        durations_dispo = (
            df_d1.dropna(subset=["SEGMENT_DURATION"])
            .groupby("SEGMENT_DURATION")["NUM_SEGMENT"]
            .min()
            .sort_values()
            .index.tolist()
        )
    else:
        durations_dispo = sorted(df_d1["SEGMENT_DURATION"].dropna().unique().tolist())

    # --- Filtres ---
    col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 1])
    with col_f1:
        filtre_sous_classe = st.multiselect(
            "Sous-classe d'actif",
            options=sous_classes_dispo,
            default=[],
            key="detail_taux_sous_classe",
        )
    with col_f2:
        filtre_type_gestion = st.multiselect(
            "Type de gestion",
            options=type_gestion_dispo,
            default=[],
            key="detail_taux_type_gestion",
        )
    with col_f3:
        filtre_duration = st.multiselect(
            "Segment duration",
            options=durations_dispo,
            default=[],
            key="detail_taux_duration",
        )
    with col_f4:
        _cfg_top_n  = st.session_state.get("app_config", {}).get("default_top_n", 20)
        _opts_topn  = [10, 20, 50, 100, 0]
        top_n = st.selectbox(
            "Top N titres",
            options=_opts_topn,
            format_func=lambda x: "Tous" if x == 0 else str(x),
            index=_opts_topn.index(_cfg_top_n) if _cfg_top_n in _opts_topn else 1,
            key="detail_taux_topn",
        )
        sort_asc = st.checkbox("Ordre croissant", value=False, key="detail_taux_sort_asc")

    st_col1, st_col2 = st.columns(2)
    with st_col1:
        search_lib = st.text_input("Libellé (recherche)", value="", key="detail_taux_lib")
    with st_col2:
        search_id = st.text_input("ID (recherche)", value="", key="detail_taux_id")

    # --- Construction du tableau ---
    result = _build_detail_titres_table(
        dff, d0, d1,
        filtre_sous_classe,
        filtre_type_gestion,
        filtre_duration,
        search_lib,
        search_id,
        top_n,
        sort_asc,
    )

    if result is None:
        st.info("Aucun titre ne correspond aux filtres sélectionnés.")
        return

    df_detail, nb_total = result
    # Nombre de titres = lignes hors "Autres" et "TOTAL"
    nb_affiches = len(df_detail[~df_detail["Libellé"].isin(["Autres", "TOTAL", "Positions liquidées"])])

    st.caption(
        f"{nb_affiches} titre(s) affiché(s)"
        + (f" sur {nb_total}" if top_n > 0 and nb_affiches < nb_total else "")
        + f" — total VM : {fmt_meur(df_detail.loc[df_detail['Libellé'] == 'TOTAL', 'VM (M€)'].sum())}"
    )

    # Seuil VaR 99% hors lignes spéciales
    _mask_data = ~df_detail["Libellé"].isin(["Autres", "TOTAL"])
    _var99_vals = pd.to_numeric(df_detail.loc[_mask_data, "VaR 99% (M€)"], errors="coerce")
    _q = st.session_state.get("app_config", {}).get("var_quantile", 0.75)
    seuil_var99 = _var99_vals.quantile(_q)

    def _highlight_var99(val):
        try:
            if float(val) >= seuil_var99:
                return "background-color: #f8d7da; color: #842029; font-weight: bold"
        except (TypeError, ValueError):
            pass
        return ""

    from modules.format_utils import fmt_pct
    styler_det = apply_common_table_styles(
        df_detail,
        fmt_map={
            "VM (M€)":       fmt_meur,
            "Δ VM (M€)":     fmt_meur,
            "VaR 95% (M€)":  fmt_meur,
            "VaR 99% (M€)":  fmt_meur,
            "Alloc (%)":     fmt_pct,
            "Δ Alloc (%)":   fmt_pct,
            "Δ VM (%)":      fmt_pct,
        },
        total_cols=("Libellé",),
        delta_meur_col="Δ VM (M€)",
        delta_pct_col="Δ VM (%)",
    ).map(_highlight_var99, subset=["VaR 99% (M€)"])
    render_static_dataframe(styler_det)

    excel_bytes = df_to_excel_bytes(df_detail, sheet_name="Risque_Taux_Titres")
    st.download_button(
        label="📥 Télécharger en Excel",
        data=excel_bytes,
        file_name="risque_taux_detail_titres.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ==========================================================
# Render principal
# ==========================================================

def render_risque_taux_tab(df_selection: pd.DataFrame, date_debut, date_fin):
    st.subheader("Risque Taux")

    # 1) Préparation de la base
    prep = _prepare_taux_base(df_selection, date_debut, date_fin)
    if prep is None:
        return

    dff, d0, d1, dim_col = prep

    st.write(
        f"Période : **{d0.strftime('%d-%m-%Y')}** ⮕ "
        f"**{d1.strftime('%d-%m-%Y')}**"
    )

    # 2) Bloc Duration x Type de gestion
    duration_block = build_taux_duration_block(dff, dim_col, d0, d1)
    if duration_block is None:
        return

    view_table = duration_block["view_table"]
    cols_gestion = duration_block["cols_gestion"]
    order_duration = duration_block["order_duration"]
    fig_stack = duration_block["fig_stack"]
    fig_total = duration_block["fig_total"]

    styled_table = _style_table_with_total(view_table, cols_gestion)

    st.markdown("**VM par segment de duration et type de gestion (M€)**")
    col_table, col_graphs = st.columns([1, 1.15])

    # --- Tableau + export ---
    with col_table:
        render_static_dataframe(styled_table)

        excel_bytes = df_to_excel_bytes(view_table, sheet_name="Risque_Taux_Duration")
        st.download_button(
            label="📥Télécharger en Excel",
            data=excel_bytes,
            file_name="risque_taux_duration.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_graphs:
        col_stack, col_total = st.columns([2, 1])
        with col_stack:
            st.plotly_chart(fig_stack, use_container_width=True, config={"displayModeBar": "hover"})
        with col_total:
            st.plotly_chart(fig_total, use_container_width=True, config={"displayModeBar": "hover"})

    # --------------------------------------------------------------
    # 3) Var. période & stress (VaR 95 / VaR 99)
    # --------------------------------------------------------------
    st.markdown("---")
    st.markdown("### Variation par période & Stress par segment de duration")

    var_block = build_taux_var_block(dff, dim_col, d0, d1, order_duration)
    df_var_view = var_block["df_var_view"]
    fig_var_seg = var_block["fig_var_seg"]
    fig_var_tot = var_block["fig_var_tot"]

    col_var_tab, col_var_graph = st.columns([1, 1.15])

    # Tableau Var/VaR
    with col_var_tab:
        styled_var = apply_common_table_styles(
            df_var_view,
            fmt_map = {
            "Δ VM (M€)": fmt_meur,
            "VaR 95% (M€)": fmt_meur,
            "VaR 99% (M€)": fmt_meur,
        },
            total_cols=("Duration",),   # Car total est dans Duration
            delta_meur_col="Δ VM (M€)",
            stable_threshold_meur=0.05,
        )

        render_static_dataframe(styled_var)

        # Export Excel – Var / VaR
        excel_bytes_var = df_to_excel_bytes(
            df_var_view,
            sheet_name="Risque_Taux_Var_Stress"
        )
        st.download_button(
            label="📥 Télécharger en Excel",
            data=excel_bytes_var,
            file_name="risque_taux_var_stress.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # Graphes Var/VaR
    with col_var_graph:
        col_var_seg_graph, col_var_tot_graph = st.columns([2, 1])
        with col_var_seg_graph:
            st.plotly_chart(fig_var_seg, use_container_width=True, config={"displayModeBar": "hover"})
        with col_var_tot_graph:
            st.plotly_chart(fig_var_tot, use_container_width=True, config={"displayModeBar": "hover"})

    # --------------------------------------------------------------
    # 4) Détail par titre
    # --------------------------------------------------------------
    st.markdown("---")
    show_detail = st.toggle("Afficher le détail par titre", value=False, key="taux_detail_toggle")
    if show_detail:
        _render_detail_titres_section(dff, d0, d1)

    # Stockage pour l'onglet Rapport
    st.session_state["rapport_taux"] = {
        "fig_stack":      fig_stack,
        "fig_var_seg":    fig_var_seg,
        "table_duration": view_table,
        "table_var":      df_var_view,
        "cols_gestion":   cols_gestion,
    }