# dashboard/modules/risque_spread.py

import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st

from modules.format_utils import (
    trend,
    fmt_meur,
    fmt_delta_meur,
    fmt_pct,
    fmt_bp,
    df_to_excel_bytes,
    apply_common_table_styles,
    add_alloc_columns,
)
# ====================
# Constantes
# ====================

MAPPING_PAYS_SOUV_ISO3 = {
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
        "JAPON": "JPN",
        "LUXEMBOURG": "LUX",
        "NORVÈGE": "NOR",
        "NORVEGE": "NOR",
        "PAYS-BAS": "NLD",
        "PAYS BAS": "NLD",
        "POLOGNE": "POL",
        "SUPRA-NATIONAL": None,
        "SUPRA NATIONAL": None,
    }

# ============================
# Spread  pondérés par la VM
# ============================

def weighted_spread(group: pd.DataFrame) -> float:
    w = pd.to_numeric(group["VM_INIT"], errors="coerce")
    s = pd.to_numeric(group["SPREAD_EIOPA_EPS"], errors="coerce")
    mask = (~w.isna()) & (~s.isna()) & (w != 0)
    if not mask.any():
        return np.nan
    return float(np.average(s[mask], weights=w[mask]))


def weighted_duration(group: pd.DataFrame) -> float:
    w = pd.to_numeric(group["VM_INIT"], errors="coerce")
    d = pd.to_numeric(group["DURATION_EPS"], errors="coerce")
    mask = (~w.isna()) & (~d.isna()) & (w != 0)
    if not mask.any():
        return np.nan
    return float(np.average(d[mask], weights=w[mask]))


# =========================
# Top 10 par segment (Souv/Corp)
# =========================

def compute_top_10_spread_segment(
    dff: pd.DataFrame,
    type_groupe_value: str,   # "Souverain" ou "Corporate"
    col_lib: str,             # "LIB_GROUPE" ou "LIB_EMETTEUR"
    d0,
    d1,
    ordre_notation,
):
    """
    Calcule Top 10 + TOTAL pour un segment (Souverain / Corporate).
    Retourne:
      - top10_df (DataFrame) prêt à afficher/exports
      - empty (bool)
    """
    dff_seg = dff[dff["TYPE_GROUPE"].astype(str) == type_groupe_value].copy()
    if dff_seg.empty:
        return None, True

    dff_seg_d0 = dff_seg[dff_seg["DATE_TRANSPA"] == d0].copy()
    dff_seg_d1 = dff_seg[dff_seg["DATE_TRANSPA"] == d1].copy()

    dff_seg_d0["Groupe"] = dff_seg_d0[col_lib].fillna("n.d.")
    dff_seg_d1["Groupe"] = dff_seg_d1[col_lib].fillna("n.d.")

    grp_cols = ["Groupe", "NOTATION", "PAYS"]

    debut_seg = (
        dff_seg_d0.groupby(grp_cols, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_DEBUT")
    )
    fin_seg = (
        dff_seg_d1.groupby(grp_cols, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_FIN")
    )
    fin_spread = (
        dff_seg_d1.groupby(grp_cols, dropna=False)
        .apply(weighted_spread)
        .rename("Spread")
    )
    duration_seg = (
        dff_seg_d1.groupby(grp_cols, dropna=False)
        .apply(weighted_duration)
        .rename("Duration")
    )

    res_seg = (
        pd.concat([debut_seg, fin_seg, fin_spread, duration_seg], axis=1)
        .fillna(0)
        .reset_index()
    )

    res_seg["Delta_VM"] = res_seg["VM_FIN"] - res_seg["VM_DEBUT"]
    res_seg["Delta_VM_pct"] = np.where(
        res_seg["VM_DEBUT"] != 0,
        res_seg["Delta_VM"] / res_seg["VM_DEBUT"],
        np.nan
    )
    res_seg["Tendance"] = res_seg["Delta_VM_pct"].apply(trend)

    res_seg["NOTATION"] = res_seg["NOTATION"].fillna("n.d.")
    res_seg["NOTATION"] = pd.Categorical(
        res_seg["NOTATION"],
        categories=ordre_notation,
        ordered=True
    )

    # Totaux (en brut, avant passage M€/%)
    total_VM_debut = res_seg["VM_DEBUT"].sum().round()
    total_VM_fin = res_seg["VM_FIN"].sum().round()
    total_VM_delta = total_VM_fin - total_VM_debut
    total_VM_pct = (total_VM_delta / total_VM_debut) if total_VM_debut != 0 else np.nan

    spread_all = pd.to_numeric(res_seg["Spread"], errors="coerce")
    vm_all = pd.to_numeric(res_seg["VM_FIN"], errors="coerce")
    mask_all = (~spread_all.isna()) & (vm_all > 0)
    total_spread = float(np.average(spread_all[mask_all], weights=vm_all[mask_all])) if mask_all.any() else np.nan

    # Agrégation par Groupe (pour éviter les doublons)
    corps = res_seg.copy()

    agg = (
        corps.groupby("Groupe", as_index=False)
        .agg(
            VM_DEBUT=("VM_DEBUT", "sum"),
            VM_FIN=("VM_FIN", "sum"),
            Delta_VM=("Delta_VM", "sum")
        )
    )
    agg["Delta_VM_pct"] = np.where(
        agg["VM_DEBUT"] != 0,
        agg["Delta_VM"] / agg["VM_DEBUT"],
        np.nan
    )

    def weighted_spread_top(group):
        w = pd.to_numeric(group["VM_FIN"], errors="coerce")
        s = pd.to_numeric(group["Spread"], errors="coerce")
        mask = (~w.isna()) & (~s.isna()) & (w > 0)
        return float(np.average(s[mask], weights=w[mask])) if mask.any() else np.nan

    spread_agg = (
        corps.groupby("Groupe", dropna=False)
        .apply(weighted_spread_top)
        .rename("Spread")
        .reset_index()
    )

    agg = agg.merge(spread_agg, on="Groupe", how="left")
    agg["Tendance"] = agg["Delta_VM_pct"].apply(trend)

    # Passage en M€ et %
    view_top = agg.copy()
    for c in ["VM_DEBUT", "VM_FIN", "Delta_VM"]:
        view_top[c] = view_top[c] / 1e6
    view_top["Delta_VM_pct"] = view_top["Delta_VM_pct"] * 100
    
    # Top 10 avec ligne Autres pour le reste
    view_top_sorted = view_top.sort_values("VM_FIN", ascending=False).reset_index(drop=True)
    top10 = view_top_sorted.head(10).copy()
    autres = view_top_sorted.iloc[10:].copy()

    if not autres.empty:
        a_vm_debut = autres["VM_DEBUT"].sum()
        a_vm_fin   = autres["VM_FIN"].sum()
        a_delta    = autres["Delta_VM"].sum()
        a_pct      = (a_delta / a_vm_debut * 100.0) if a_vm_debut != 0 else np.nan
        w = pd.to_numeric(autres["VM_FIN"], errors="coerce")
        s = pd.to_numeric(autres["Spread"], errors="coerce")
        mask_a = (~w.isna()) & (~s.isna()) & (w > 0)
        a_spread = float(np.average(s[mask_a], weights=w[mask_a])) if mask_a.any() else np.nan
        autres_row = pd.DataFrame([{
            "Groupe": "Autres",
            "VM_DEBUT": a_vm_debut,
            "VM_FIN": a_vm_fin,
            "Delta_VM": a_delta,
            "Delta_VM_pct": a_pct,
            "Tendance": trend(a_pct / 100.0 if pd.notna(a_pct) else np.nan),
            "Spread": a_spread,
        }])
        top10 = pd.concat([top10, autres_row], ignore_index=True)

    total_view = pd.DataFrame([{
        "Groupe": "TOTAL",
        "VM_DEBUT": total_VM_debut / 1e6,
        "VM_FIN": total_VM_fin / 1e6,
        "Delta_VM": total_VM_delta / 1e6,
        "Delta_VM_pct": (total_VM_pct * 100) if not np.isnan(total_VM_pct) else np.nan,
        "Spread": total_spread,
    }])
    total_view["Tendance"] = total_view["Delta_VM_pct"].apply(
        lambda x: trend(x / 100.0) if pd.notna(x) else trend(np.nan)
    )

    top10 = pd.concat([top10, total_view], ignore_index=True)
    top10 = add_alloc_columns(top10, vm_fin_col="VM_FIN", delta_vm_col="Delta_VM")
    return top10, False

# =========================
# Helpers pour l'onglet Spread
# =========================

def _prepare_spread_base(
    df_selection: pd.DataFrame,
    date_debut,
    date_fin,
    choix_dim_affichage: str,
):
    """
    Prépare la base pour le bloc principal Risque Spread :
      - filtre RSQ_FIN_TAUX == 1
      - choisit la dimension (Type de groupe / Type d'émetteur)
      - calcule d0 / d1 effectives
    Retourne :
      dff, d0, d1, dim_col, col_lib, ordre_notation
    ou None si problème.
    """
    mapping_dim = {
        "Type de groupe": "TYPE_GROUPE",
        "Type d'émetteur": "TYPE_EMETTEUR",
    }
    if choix_dim_affichage not in mapping_dim:
        return None

    dim_col = mapping_dim[choix_dim_affichage]
    col_lib = "LIB_GROUPE" if dim_col == "TYPE_GROUPE" else "LIB_EMETTEUR"

    dff = df_selection.copy()

    # Obligations uniquement
    if "RSQ_FIN_TAUX" not in dff.columns:
        return None
    dff = dff[dff["RSQ_FIN_TAUX"].astype(str) == "1"].copy()
    if dff.empty:
        return None

    if dim_col not in dff.columns:
        return None

    dff[dim_col] = dff[dim_col].fillna("n.d.")

    if "DATE_TRANSPA" not in dff.columns:
        return None

    dff["DATE_TRANSPA"] = pd.to_datetime(dff["DATE_TRANSPA"]).dt.date
    date_debut = pd.to_datetime(date_debut).date()
    date_fin = pd.to_datetime(date_fin).date()

    d0 = dff.loc[dff["DATE_TRANSPA"] <= date_debut, "DATE_TRANSPA"].max()
    d1 = dff.loc[dff["DATE_TRANSPA"] <= date_fin, "DATE_TRANSPA"].max()

    if pd.isna(d0) or pd.isna(d1):
        return None

    # Ordre des notations standardisé
    ordre_notation = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "HY", "n.d"]

    return dff, d0, d1, dim_col, col_lib, ordre_notation


def build_spread_global_section(
    dff: pd.DataFrame,
    d0,
    d1,
    dim_col: str,
    dim_label: str,
    ordre_notation,
):
    """
    Construit le bloc 'tableau global + nuage Spread / Duration' SANS Streamlit.

    Retourne :
      - d0_ts, d1_ts      : Timestamp (pour affichage période)
      - view_final        : DataFrame prêt pour export/formatage
      - fig_scatter       : figure Plotly (nuage Spread/Duration)
    OU None si problème.
    """
    d0_ts = pd.to_datetime(d0)
    d1_ts = pd.to_datetime(d1)

    # -------------------------
    # Table principale Spread
    # -------------------------
    grp_spread = [dim_col, "NOTATION"]

    debut = (
        dff[dff["DATE_TRANSPA"] == d0]
        .groupby(grp_spread, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_DEBUT")
    )
    fin = (
        dff[dff["DATE_TRANSPA"] == d1]
        .groupby(grp_spread, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_FIN")
    )
    fin_spread = (
        dff[dff["DATE_TRANSPA"] == d1]
        .groupby(grp_spread, dropna=False)
        .apply(weighted_spread)
        .rename("Spread")
    )
    duration_spread = (
        dff[dff["DATE_TRANSPA"] == d1]
        .groupby(grp_spread, dropna=False)
        .apply(weighted_duration)
        .rename("Duration")
    )

    res_spread = (
        pd.concat([debut, fin, fin_spread, duration_spread], axis=1)
        .fillna(0)
        .reset_index()
    )
    res_spread = res_spread[res_spread["VM_FIN"] != 0]

    # Tri notations via NUM_NOTATION si présent
    if "NUM_NOTATION" in dff.columns:
        notation_map = (
            dff[["NOTATION", "NUM_NOTATION"]]
            .dropna(subset=["NOTATION", "NUM_NOTATION"])
            .drop_duplicates()
        )
        res_spread = res_spread.merge(notation_map, on="NOTATION", how="left")
    else:
        res_spread["NUM_NOTATION"] = np.nan

    # variations
    res_spread["Delta_VM"] = res_spread["VM_FIN"] - res_spread["VM_DEBUT"]
    res_spread["Delta_VM_pct"] = np.where(
        res_spread["VM_DEBUT"] != 0,
        res_spread["Delta_VM"] / res_spread["VM_DEBUT"],
        np.nan,
    )
    res_spread["Tendance"] = res_spread["Delta_VM_pct"].apply(trend)

    # notation ordonnée
    res_spread["NOTATION"] = res_spread["NOTATION"].fillna("n.d")
    res_spread["NOTATION"] = pd.Categorical(
        res_spread["NOTATION"],
        categories=ordre_notation,
        ordered=True,
    )

    # ordre dimension (Souverain / Corporate si applicable)
    if dim_col in ("TYPE_GROUPE", "TYPE_EMETTEUR"):
        ordre_dim = ["Souverain", "Corporate", "n.d."]
        res_spread[dim_col] = res_spread[dim_col].fillna("n.d.")
        res_spread[dim_col] = pd.Categorical(
            res_spread[dim_col],
            categories=ordre_dim,
            ordered=True,
        )

    res_spread = res_spread.sort_values(
        by=[dim_col, "NUM_NOTATION"], ascending=[True, True]
    )

    # TOTAL
    total_VM_debut = res_spread["VM_DEBUT"].sum().round()
    total_VM_fin = res_spread["VM_FIN"].sum().round()
    total_VM_delta = (total_VM_fin - total_VM_debut).round()
    total_VM_pct = (
        total_VM_delta / total_VM_debut if total_VM_debut != 0 else np.nan
    )

    spread_num = pd.to_numeric(res_spread["Spread"], errors="coerce")
    weights = pd.to_numeric(res_spread["VM_FIN"], errors="coerce")
    mask = (~spread_num.isna()) & (weights > 0)
    total_spread = (
        float(np.average(spread_num[mask], weights=weights[mask]))
        if mask.any()
        else np.nan
    )

    total_row = pd.DataFrame(
        [
            {
                dim_col: "TOTAL",
                "NOTATION": "",
                "VM_DEBUT": total_VM_debut,
                "VM_FIN": total_VM_fin,
                "Delta_VM": total_VM_delta,
                "Delta_VM_pct": total_VM_pct,
                "Tendance": trend(total_VM_pct),
                "Spread": total_spread,
                "Duration": np.nan,
                "NUM_NOTATION": np.nan,
            }
        ]
    )

    res_spread = pd.concat([res_spread, total_row], ignore_index=True)

    # TOTAL en dernier — réapplication de l'ordre Categorical perdu après concat
    corps = res_spread[res_spread[dim_col] != "TOTAL"].copy()
    if dim_col in ("TYPE_GROUPE", "TYPE_EMETTEUR"):
        corps[dim_col] = pd.Categorical(
            corps[dim_col],
            categories=["Souverain", "Corporate", "n.d."],
            ordered=True,
        )
    corps = corps.sort_values(by=[dim_col, "NUM_NOTATION"], ascending=[True, True])
    total_ligne = res_spread[res_spread[dim_col] == "TOTAL"]
    res_spread = pd.concat([corps, total_ligne], ignore_index=True)

    # Vue affichage
    view_spread = res_spread.copy()
    for c in ["VM_DEBUT", "VM_FIN", "Delta_VM"]:
        view_spread[c] = view_spread[c] / 1e6
    view_spread["Delta_VM_pct"] = view_spread["Delta_VM_pct"] * 100

    view_spread = add_alloc_columns(view_spread, vm_fin_col="VM_FIN", delta_vm_col="Delta_VM")

    view_final = view_spread[
        [dim_col, "NOTATION", "VM_FIN", "Delta_VM", "Delta_VM_pct", "Tendance", "Alloc (%)", "Δ Alloc (%)", "Spread"]
    ].copy()
    view_final = view_final.rename(
        columns={
            dim_col: dim_label,
            "NOTATION": "Notation",
            "VM_FIN": "Valeur de marché (M€)",
            "Delta_VM": "Δ VM (M€)",
            "Delta_VM_pct": "Δ VM (%)",
            "Tendance": "Tendance",
            "Spread": "Spread (bp)",
        }
    )

    # Nuage de points
    df_points = res_spread[res_spread[dim_col] != "TOTAL"].copy()
    df_points["VM_MEUR"] = df_points["VM_FIN"] / 1e6

    # Couleurs distinctes par notation (vert=sûr → rouge=risqué)
    _NOTATION_COLORS = {
        "AAA": "#2ca02c", "AA+": "#4aad4a", "AA": "#1f77b4",  "AA-": "#5ba8d4",
        "A+":  "#ff7f0e", "A":   "#ffa040", "A-": "#ffba70",
        "BBB+":"#d62728", "BBB": "#e05252", "BBB-":"#e88080",
        "BB+": "#9467bd", "BB":  "#8c564b", "NR":  "#7f7f7f",
    }
    fig_scatter = px.scatter(
        df_points,
        x="Duration",
        y="Spread",
        color="NOTATION",
        size="VM_MEUR",
        size_max=70,
        custom_data=[dim_col, "NOTATION", "VM_MEUR"],
        color_discrete_map=_NOTATION_COLORS,
        color_discrete_sequence=[
            "#2ca02c", "#1f77b4", "#ff7f0e", "#d62728",
            "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
        ],
        labels={
            "Duration": "Duration (années)",
            "Spread": "Spread (bp)",
            dim_col: dim_label,
            "NOTATION": "Notation",
            "VM_FIN": "Valeur de marché",
        },
    )
    fig_scatter.update_layout(margin=dict(t=0, b=40, l=40, r=10))
    fig_scatter.update_traces(
        marker=dict(line=dict(width=1, color="white")),
        hovertemplate=(
            "<b>%{customdata[0]}<br>"
            "Notation : %{customdata[1]}<br>"
            "Duration : %{x:.0f} ans<br>"
            "Spread : %{y:,.0f} bp<br>"
            "VM : %{customdata[2]:,.2f} M€</b><extra></extra>"
        )
    )

    # -------------------------
    # Treemap : dim_col → NOTATION → LIBELLE
    # -------------------------
    fig_treemap = None
    libelle_col = "LIBELLE" if "LIBELLE" in dff.columns else None
    notation_col = "NOTATION" if "NOTATION" in dff.columns else None

    if libelle_col and notation_col:
        df_tree = dff[dff["DATE_TRANSPA"] == d1].copy()
        df_tree["VM_INIT"] = pd.to_numeric(df_tree["VM_INIT"], errors="coerce").fillna(0.0)
        df_tree = df_tree[df_tree["VM_INIT"] > 0]

        if not df_tree.empty:
            for col in [dim_col, notation_col, libelle_col]:
                df_tree[col] = df_tree[col].fillna("n.d.").astype(str).str.strip().replace("", "n.d.")

            df_tree_agg = (
                df_tree
                .groupby([dim_col, notation_col, libelle_col], dropna=False)["VM_INIT"]
                .sum()
                .reset_index()
            )
            df_tree_agg["VM_MEUR"] = df_tree_agg["VM_INIT"] / 1e6
            df_tree_agg = df_tree_agg[df_tree_agg["VM_MEUR"] > 0]

            _SPREAD_PALETTE = [
                "#714A80", "#2C6FAC", "#3A9E5F", "#D4704B",
                "#8B6BB5", "#2A9BAB", "#B55C3A", "#C95B8B",
                "#4D8B7A", "#7B8B3A", "#5B7AB5", "#B58B3A",
            ]

            if not df_tree_agg.empty:
                fig_treemap = px.treemap(
                    df_tree_agg,
                    path=[dim_col, notation_col, libelle_col],
                    values="VM_MEUR",
                    color_discrete_sequence=_SPREAD_PALETTE,
                    labels={
                        dim_col: dim_label,
                        notation_col: "Notation",
                        libelle_col: "Titre",
                        "VM_MEUR": "VM (M€)",
                    },
                )
                fig_treemap.update_traces(
                    texttemplate="<b>%{label}</b><br>%{percentRoot:.1%}",
                    textfont=dict(size=10, color="white"),
                    marker=dict(line=dict(width=1, color="white")),
                    hovertemplate=(
                        "<b>%{label}</b><br>"
                        "<b>VM : %{value:,.1f} M€</b><br>"
                        "<b>Part du total : %{percentRoot:.1%}</b><br>"
                        "<b>Part du parent : %{percentParent:.1%}</b>"
                        "<extra></extra>"
                    ),
                )
                fig_treemap.update_layout(margin=dict(t=30, l=10, r=10, b=10))

    return d0_ts, d1_ts, view_final, fig_scatter, fig_treemap

# Bloc Souverain
def build_spread_souverain_block(
    dff: pd.DataFrame,
    d0,
    d1,
    dim_col: str,
    col_lib: str,
    ordre_notation,
):
    """
    Construit le bloc 'Risque de Spread (Souverain)' sans Streamlit :
      - top10_souv_df : DataFrame prêt pour affichage/export (colonnes finales)
      - fig_geo       : figure Plotly de la carte (ou None si pas traçable)
    Retourne (top10_souv_df, fig_geo) ou (None, None) si aucune expo souveraine.
    """
    # Top 10 via helper existant
    top10_souv, empty_souv = compute_top_10_spread_segment(
        dff=dff,
        type_groupe_value="Souverain",
        col_lib=col_lib,
        d0=d0,
        d1=d1,
        ordre_notation=ordre_notation,
    )
    if empty_souv:
        return None, None

    # Nom de colonne d'affichage
    nom_col_aff_souv = (
        "Libellé du groupe" if dim_col == "TYPE_GROUPE" else "Libellé de l'émetteur"
    )

    top10_souv = top10_souv.rename(
        columns={
            "Groupe": nom_col_aff_souv,
            "VM_FIN": "Valeur de marché (M€)",
            "Delta_VM": "Δ VM (M€)",
            "Delta_VM_pct": "Δ VM (%)",
            "Spread": "Spread (bp)",
        }
    )

    cols_keep = [
        nom_col_aff_souv,
        "Valeur de marché (M€)",
        "Δ VM (M€)",
        "Δ VM (%)",
        "Tendance",
        "Alloc (%)",
        "Δ Alloc (%)",
        "Spread (bp)",
    ]
    top10_souv = top10_souv[[c for c in cols_keep if c in top10_souv.columns]]

    # ----------------- Carte -----------------
    fig_geo = None

    dff_souv_map = dff[
        (dff["TYPE_GROUPE"].astype(str) == "Souverain")
        & (dff["DATE_TRANSPA"] == d1)
    ].copy()

    if not dff_souv_map.empty and "PAYS" in dff_souv_map.columns:
        df_geo = (
            dff_souv_map.groupby("PAYS", as_index=False)["VM_INIT"]
            .sum()
            .rename(columns={"VM_INIT": "VM_FIN"})
        )
        df_geo["VM_FIN_MEUR"] = df_geo["VM_FIN"] / 1e6
        df_geo["PAYS_CLEAN"] = df_geo["PAYS"].astype(str).str.strip().str.upper()
        df_geo["PAYS_ISO_3"] = df_geo["PAYS_CLEAN"].map(MAPPING_PAYS_SOUV_ISO3)

        df_countries = df_geo[df_geo["PAYS_ISO_3"].notna()].copy()
        df_supra = df_geo[df_geo["PAYS_CLEAN"].str.contains("SUPRA", na=False)]
        supra_total = float(df_supra["VM_FIN_MEUR"].sum()) if not df_supra.empty else 0.0

        if not df_countries.empty or supra_total > 0:
            vm_max = float(df_countries["VM_FIN_MEUR"].max()) if not df_countries.empty else 0.0
            seuil_min = vm_max * 0.004 if vm_max else 0.0

            if not df_countries.empty:
                df_countries["VM_SIZE"] = np.where(
                    df_countries["VM_FIN_MEUR"] > 0,
                    np.maximum(df_countries["VM_FIN_MEUR"], seuil_min),
                    0,
                )

                fig_geo = px.scatter_geo(
                    df_countries,
                    locations="PAYS_ISO_3",
                    locationmode="ISO-3",
                    size="VM_SIZE",
                    size_max=40,
                    text="PAYS_ISO_3",
                    custom_data=["PAYS", "VM_FIN_MEUR"],
                )
                fig_geo.update_traces(marker=dict(color="red"))
                fig_geo.update_traces(
                    hovertemplate=(
                        "<b>%{customdata[0]}<br>"
                        "VM : %{customdata[1]:,.2f} M€</b><extra></extra>"
                    ),
                    mode="markers+text",
                    textposition="middle center",
                    textfont=dict(family="Arial Black", color="white", size=10, weight=700),
                )
            else:
                fig_geo = px.scatter_geo()

            # bulle supra-national
            if supra_total > 0:
                if vm_max and vm_max > 0:
                    supra_size = 70 * supra_total / vm_max
                    supra_size = max(25, supra_size)
                else:
                    supra_size = 30

                fig_geo.add_scattergeo(
                    lon=[2],
                    lat=[70],
                    mode="markers+text",
                    marker=dict(size=supra_size, color="black", opacity=0.85),
                    name="Supra-national",
                    text=["SUPRA-NATIONAL"],
                    textposition="middle center",
                    textfont=dict(family="Arial Black", color="white", size=10, weight=700),
                    customdata=[[supra_total]],
                    hovertemplate=(
                        "<b>%{text}<br> VM : %{customdata[0]:,.2f} M€</b><extra></extra>"
                    ),
                )

            fig_geo.update_geos(
                scope="world",
                fitbounds="locations",
                showcountries=True,
                showcoastlines=True,
                showland=True,
                landcolor="#C0C0C0",
                bgcolor="#DADADA",
            )
            fig_geo.update_layout(
                height=500,
                margin=dict(t=0, b=0, l=0, r=0),
                legend=dict(
                    x=0.01,
                    y=0.01,
                    xanchor="left",
                    yanchor="bottom",
                    bgcolor="rgba(255,255,255,0.75)",
                    bordercolor="#cccccc",
                    borderwidth=1,
                ),
            )

    return top10_souv, fig_geo

# Bloc Corporate
def build_spread_corporate_block(
dff: pd.DataFrame,
d0,
d1,
dim_col: str,
col_lib: str,
ordre_notation,
):
    """
    Construit le bloc 'Risque Spread (Corporate)' sans Streamlit :
    - top10_corp_df : DataFrame prêt pour affichage/export (colonnes finales)
    - fig_treemap   : treemap Plotly (ou None si pas traçable)
    Retourne (top10_corp_df, fig_treemap) ou (None, None) si aucune expo corporate.
    """
    top10_corp, empty_corp = compute_top_10_spread_segment(
        dff=dff,
        type_groupe_value="Corporate",
        col_lib=col_lib,
        d0=d0,
        d1=d1,
        ordre_notation=ordre_notation,
    )
    if empty_corp:
        return None, None

    nom_col_aff_corp = (
        "Libellé du groupe" if dim_col == "TYPE_GROUPE" else "Libellé de l'émetteur"
    )

    top10_corp = top10_corp.rename(
        columns={
            "Groupe": nom_col_aff_corp,
            "VM_FIN": "Valeur de marché (M€)",
            "Delta_VM": "Δ VM (M€)",
            "Delta_VM_pct": "Δ VM (%)",
            "Spread": "Spread (bp)",
        }
    )

    cols_keep = [
        nom_col_aff_corp,
        "Valeur de marché (M€)",
        "Δ VM (M€)",
        "Δ VM (%)",
        "Tendance",
        "Alloc (%)",
        "Δ Alloc (%)",
        "Spread (bp)",
    ]
    top10_corp = top10_corp[[c for c in cols_keep if c in top10_corp.columns]]

    # ---------------- Treemap Corporate ----------------
    fig_conc = None

    df_conc = dff[
        (dff["TYPE_GROUPE"].astype(str) == "Corporate")
        & (dff["DATE_TRANSPA"] == d1)
    ].copy()

    if not df_conc.empty:
        df_conc["LIB_EMETTEUR"] = df_conc["LIB_EMETTEUR"].fillna("n.d.")

        mapping_gest2 = {
            "1": "Mandats",
            "2": "Direct hors OPC",
            "3": "Fonds dédiés",
            "4": "Direct OPC",
        }
        if "TYPE_GESTION_2" in df_conc.columns:
            df_conc["TYPE_GESTION_2"] = df_conc["TYPE_GESTION_2"].astype(str)
        else:
            df_conc["TYPE_GESTION_2"] = "Autres"

        df_conc["TYPE_GESTION_LIB"] = df_conc["TYPE_GESTION_2"].map(mapping_gest2).fillna("Autres")

        treemap_df = (
            df_conc.groupby(["LIB_EMETTEUR", "TYPE_GESTION_LIB", "LIBELLE"], dropna=False)["VM_INIT"]
            .sum()
            .reset_index()
            .rename(columns={"VM_INIT": "VM_MEUR"})
        )
        treemap_df["VM_MEUR"] = treemap_df["VM_MEUR"] / 1e6
        treemap_df = treemap_df[treemap_df["VM_MEUR"] > 0]

        if not treemap_df.empty:
            # Palette par émetteur (nœud parent) : chaque émetteur reçoit une couleur
            # distincte ; ses enfants (type gestion, titres) en héritent automatiquement.
            # Évite les cases blanches qui apparaissent quand le nœud parent n'a pas
            # de valeur dans color_discrete_map.
            _CORP_PALETTE = [
                "#714A80", "#2C6FAC", "#3A9E5F", "#D4704B",
                "#8B6BB5", "#2A9BAB", "#B55C3A", "#C95B8B",
                "#4D8B7A", "#7B8B3A", "#5B7AB5", "#B58B3A",
            ]

            fig_conc = px.treemap(
                treemap_df,
                path=["LIB_EMETTEUR", "TYPE_GESTION_LIB", "LIBELLE"],
                values="VM_MEUR",
                color_discrete_sequence=_CORP_PALETTE,
                labels={
                    "TYPE_GESTION_LIB": "Type de gestion",
                    "LIB_EMETTEUR": "Émetteur",
                    "VM_MEUR": "Valeur de marché (M€)",
                },
            )
            fig_conc.update_layout(margin=dict(t=0, b=40, l=0, r=0))
            fig_conc.update_traces(
                customdata=treemap_df[["VM_MEUR"]].to_numpy(),
                texttemplate="<b>%{label}</b><br>%{percentRoot:.1%}",
                textfont=dict(size=10, color="white"),
                marker=dict(line=dict(width=1, color="white")),
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "<b>VM : %{value:,.1f} M€</b><br>"
                    "<b>Part du total : %{percentRoot:.1%}</b><br>"
                    "<b>Part du parent : %{percentParent:.1%}</b><extra></extra>"
                ),
            )
            fig_conc.update_layout(margin=dict(t=0, l=0, r=0, b=0))

    return top10_corp, fig_conc

    
# =========================
# Render principal onglet
# =========================

def render_risque_spread_tab(df_selection: pd.DataFrame, date_debut, date_fin):
    st.subheader("Risque de Spread (Souverain et Corporate)")

    # -------------------------
    # Choix dimension d'analyse
    # -------------------------
    choix_dim_affichage = st.radio(
        "Vue par :",
        options=["Type de groupe", "Type d'émetteur"],
        index=0,
        horizontal=True,
    )

    # -------------------------
    # Préparation de la base
    # -------------------------
    base = _prepare_spread_base(df_selection, date_debut, date_fin, choix_dim_affichage)
    if base is None:
        st.info("Aucune donnée disponible pour le Risque Spread sur la période sélectionnée.")
        return

    dff, d0, d1, dim_col, col_lib, ordre_notation = base

    st.write(
        f"Période : **{pd.to_datetime(d0).strftime('%d-%m-%Y')}** ⮕ "
        f"**{pd.to_datetime(d1).strftime('%d-%m-%Y')}**"
    )

    # -------------------------
    # Bloc global : tableau + nuage
    # -------------------------
    d0_ts, d1_ts, view_final, fig_scatter, fig_treemap_global = build_spread_global_section(
        dff=dff,
        d0=d0,
        d1=d1,
        dim_col=dim_col,
        dim_label=choix_dim_affichage,
        ordre_notation=ordre_notation,
    )

    fmt_map = {
        "Valeur de marché (M€)": fmt_meur,
        "Δ VM (M€)": fmt_delta_meur,
        "Δ VM (%)": fmt_pct,
        "Alloc (%)": fmt_pct,
        "Δ Alloc (%)": fmt_pct,
        "Spread (bp)": fmt_bp,
    }
    styled = apply_common_table_styles(
        view_final,
        fmt_map=fmt_map,
        total_cols=(choix_dim_affichage,), # permezt de detecter TOTAL pour le formater en gras
        delta_meur_col="Δ VM (M€)",
        delta_pct_col="Δ VM (%)",
        tendance_col="Tendance",
    )

    st.markdown("**Vue globale par exposition — Nuage de points Spread / Duration**")
    col_table, col_graph = st.columns([1.4, 0.9])

    with col_table:
        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            height=35 * (len(view_final) + 1) + 3,
        )

        excel_spread = df_to_excel_bytes(view_final, sheet_name="Risque_Spread")
        st.download_button(
            label="📥Télécharger en Excel",
            data=excel_spread,
            file_name="risque_spread_souverain_corporate.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_graph:
        fig_scatter.update_layout(height=350, margin=dict(t=10, b=40, l=40, r=10))
        st.plotly_chart(fig_scatter, use_container_width=True)

    # -------- Treemap global --------
    if fig_treemap_global is not None:
        st.markdown("**Répartition par Type d'émetteur / Rating / Titre**")
        st.plotly_chart(fig_treemap_global, use_container_width=True, key="spread_treemap_global")

    st.markdown("---")
    
    # =========================
    # Souverain: Top10 + Carte
    # =========================
    st.subheader("Risque de Spread (Souverain)")

    top10_souv, fig_geo = build_spread_souverain_block(
        dff=dff,
        d0=d0,
        d1=d1,
        dim_col=dim_col,
        col_lib=col_lib,
        ordre_notation=ordre_notation,
    )

    if top10_souv is None:
        st.info("Aucune exposition souveraine trouvée dans le portefeuille filtré.")
    else:
        nom_col_aff_souv = (
            "Libellé du groupe" if dim_col == "TYPE_GROUPE" else "Libellé de l'émetteur"
        )

        fmt_map= {
            "Valeur de marché (M€)": fmt_meur,
            "Δ VM (M€)": fmt_delta_meur,
            "Δ VM (%)": fmt_pct,
            "Alloc (%)": fmt_pct,
            "Δ Alloc (%)": fmt_pct,
            "Spread (bp)": fmt_bp,
        }
        styled_top10_souv = apply_common_table_styles(
            top10_souv,
            fmt_map=fmt_map,
            total_cols=(nom_col_aff_souv,), # permezt de detecter TOTAL pour le formater en gras
            delta_meur_col="Δ VM (M€)",
            delta_pct_col="Δ VM (%)",
            tendance_col="Tendance",
        )

        st.markdown("**Top 10 souverains par exposition**")
        col_tab_souv, col_map = st.columns([1.5, 1])

        with col_tab_souv:
            n_rows_souv = len(top10_souv)
            st.dataframe(
                styled_top10_souv,
                use_container_width=True,
                hide_index=True,
                height=35 * (n_rows_souv + 1) + 3,
            )

            excel_top10_souv = df_to_excel_bytes(top10_souv, sheet_name="Top10_Souverain")
            st.download_button(
                label="📥Télécharger en Excel",
                data=excel_top10_souv,
                file_name="top10_spread_souverain.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with col_map:
            if fig_geo is None:
                st.info("Impossible de tracer la carte : aucune information de pays exploitable.")
            else:
                st.plotly_chart(fig_geo, use_container_width=True)

    st.markdown("---")
    
    # =========================
    # Corporate: Top10 + Treemap
    # =========================
    st.subheader("Risque Spread (Corporate)")

    top10_corp, fig_conc = build_spread_corporate_block(
        dff=dff,
        d0=d0,
        d1=d1,
        dim_col=dim_col,
        col_lib=col_lib,
        ordre_notation=ordre_notation,
    )

    if top10_corp is None:
        st.info("Aucune exposition corporate trouvée dans le portefeuille filtré.")
    else:
        nom_col_aff_corp = (
            "Libellé du groupe" if dim_col == "TYPE_GROUPE" else "Libellé de l'émetteur"
        )

        fmt_map= {
            "Valeur de marché (M€)": fmt_meur,
            "Δ VM (M€)": fmt_delta_meur,
            "Δ VM (%)": fmt_pct,
            "Alloc (%)": fmt_pct,
            "Δ Alloc (%)": fmt_pct,
            "Spread (bp)": fmt_bp,
        }
        styled_top10_corp = apply_common_table_styles(
            top10_corp,
            fmt_map=fmt_map,
            total_cols=(nom_col_aff_corp,), # permezt de detecter TOTAL pour le formater en gras
            delta_meur_col="Δ VM (M€)",
            delta_pct_col="Δ VM (%)",
            tendance_col="Tendance",
        )

        st.markdown("**Top 10 Corporate par exposition**")
        col_tab_corp, col_treemap = st.columns([1.5, 1])

        with col_tab_corp:
            n_rows_corp = len(top10_corp)
            st.dataframe(
                styled_top10_corp,
                use_container_width=True,
                hide_index=True,
                height=35 * (n_rows_corp + 1) + 3,
            )

            excel_top10_corp = df_to_excel_bytes(top10_corp, sheet_name="Top10_Corporate")
            st.download_button(
                label="📥Télécharger en Excel",
                data=excel_top10_corp,
                file_name="top10_spread_corporate.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with col_treemap:
            if fig_conc is None:
                st.info("Aucune donnée exploitable pour construire la treemap corporate.")
            else:
                st.plotly_chart(fig_conc, use_container_width=True)

    # Stockage pour l'onglet Rapport
    st.session_state["rapport_spread"] = {
        "fig_scatter":    fig_scatter,
        "fig_treemap":    fig_treemap_global,
        "fig_geo":        fig_geo if top10_souv is not None else None,
        "fig_conc":       fig_conc if top10_corp is not None else None,
        "table_global":   view_final,
        "table_souverain": top10_souv,
        "table_corporate": top10_corp,
    }