# dashboard/modules/risque_immo.py

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
from modules.risque_action import _pick_first_existing_col

from modules.format_utils import (
    trend,
    apply_common_table_styles,
    render_static_dataframe,
    df_to_excel_bytes,
    add_alloc_columns,
)


# ======================================================================
# 1) Builder réutilisable : calcul + fig, SANS affichage Streamlit
# ======================================================================

def build_risque_immo_section(
    df_selection: pd.DataFrame,
    date_debut,
    date_fin,
):
    """
    Construit la section Risque Immobilier sans appel Streamlit.

    Retourne :
      - d0, d1          : dates effectives utilisées (Timestamp)
      - label_dim       : nom de la colonne de titre pour affichage ("Titre")
      - view_table      : DataFrame Top 10 + Autres + TOTAL (en M€)
      - fig_pie         : figure Plotly du camembert Top 10 + Autres (ou None)
    OU None si pas de données exploitables.
    """

    risk_col = "RSQ_FIN_IMMO"
    if risk_col not in df_selection.columns:
        # On ne loggue pas ici, la fonction appelante gérera le message
        return None

    # Colonne de dimension (Titre) : LIBELLE, sinon LIB_EMETTEUR
    titre_candidates = ["LIBELLE", "LIB_EMETTEUR"]
    dim_col = _pick_first_existing_col(df_selection, titre_candidates)
    if dim_col is None:
        return None

    label_dim = "Titre"

    dff = df_selection.copy()
    dff = dff[dff[risk_col].astype(str) == "1"].copy()
    if dff.empty:
        return None

    dff[dim_col] = dff[dim_col].fillna("n.d.")

    if "DATE_TRANSPA" not in dff.columns:
        return None

    # Dates
    dff["DATE_TRANSPA"] = pd.to_datetime(dff["DATE_TRANSPA"]).dt.date
    d0 = dff.loc[dff["DATE_TRANSPA"] <= pd.to_datetime(date_debut).date(), "DATE_TRANSPA"].max()
    d1 = dff.loc[dff["DATE_TRANSPA"] <= pd.to_datetime(date_fin).date(), "DATE_TRANSPA"].max()

    if pd.isna(d0) or pd.isna(d1):
        return None

    # ============== VM début / fin par titre (en €) ==============
    grp_cols = [dim_col]

    debut = (
        dff[dff["DATE_TRANSPA"] == d0]
        .groupby(grp_cols, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_DEBUT")
    )
    fin = (
        dff[dff["DATE_TRANSPA"] == d1]
        .groupby(grp_cols, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_FIN")
    )

    res_all = pd.concat([debut, fin], axis=1).fillna(0).reset_index()

    res_all["Delta_VM"] = res_all["VM_FIN"] - res_all["VM_DEBUT"]
    res_all["Delta_VM_pct"] = np.where(
        res_all["VM_DEBUT"] != 0,
        res_all["Delta_VM"] / res_all["VM_DEBUT"],
        np.nan,
    )
    res_all["Tendance"] = res_all["Delta_VM_pct"].apply(trend)

    # ============== Top 10 + Autres (en €) ==============
    res_sorted = res_all.sort_values(by="VM_FIN", ascending=False).reset_index(drop=True)

    if len(res_sorted) > 10:
        top10 = res_sorted.head(10).copy()
        autres = res_sorted.iloc[10:].copy()

        autres_row = {
            dim_col: "Autres",
            "VM_DEBUT": autres["VM_DEBUT"].sum(),
            "VM_FIN": autres["VM_FIN"].sum(),
            "Delta_VM": autres["Delta_VM"].sum(),
        }
        if autres_row["VM_DEBUT"] != 0:
            autres_row["Delta_VM_pct"] = autres_row["Delta_VM"] / autres_row["VM_DEBUT"]
        else:
            autres_row["Delta_VM_pct"] = np.nan

        autres_row["Tendance"] = trend(autres_row["Delta_VM_pct"])
        res_top_10_autres = pd.concat([top10, pd.DataFrame([autres_row])], ignore_index=True)
    else:
        res_top_10_autres = res_sorted.copy()

    # ============== Ligne TOTAL (en €) ==============
    total_VM_debut = res_all["VM_DEBUT"].sum().round()
    total_VM_fin = res_all["VM_FIN"].sum().round()
    total_VM_delta = (total_VM_fin - total_VM_debut).round()
    total_VM_pct = (total_VM_delta / total_VM_debut) if total_VM_debut != 0 else np.nan

    total_row = pd.DataFrame([{
        dim_col: "TOTAL",
        "VM_DEBUT": total_VM_debut,
        "VM_FIN": total_VM_fin,
        "Delta_VM": total_VM_delta,
        "Delta_VM_pct": total_VM_pct,
        "Tendance": trend(total_VM_pct),
    }])

    # Tableau = Top10 + Autres + TOTAL (en €)
    res_table = pd.concat([res_top_10_autres, total_row], ignore_index=True)

    # ============== Passage en M€ / % pour l'affichage ==============
    view = res_table.copy()
    for c in ["VM_DEBUT", "VM_FIN", "Delta_VM"]:
        view[c] = view[c] / 1e6
    view["Delta_VM_pct"] = view["Delta_VM_pct"] * 100

    view = add_alloc_columns(view, vm_fin_col="VM_FIN", delta_vm_col="Delta_VM")

    # On retire VM_DEBUT du tableau final
    view = view.drop(columns=["VM_DEBUT"])

    view = view.rename(columns={
        dim_col: label_dim,
        "VM_FIN": "VM (M€)",
        "Delta_VM": "Δ VM (M€)",
        "Delta_VM_pct": "Δ VM (%)",
        "Tendance": "Tendance",
    })

    # ============== Camembert Top 10 + Autres (en M€) ==============
    # On repart de res_top_10_autres (en €)
    if res_top_10_autres.empty:
        fig_pie = None
    else:
        df_graph_pie = res_top_10_autres.copy()
        df_graph_pie["VM_MEUR"] = df_graph_pie["VM_FIN"] / 1e6

        labels = df_graph_pie[dim_col].astype(str).tolist()
        vals = df_graph_pie["VM_MEUR"].tolist()
        total = df_graph_pie["VM_MEUR"].sum()

        if total == 0:
            fig_pie = None
        else:
            parts = [v / total for v in vals]

            hover_pie = [
                (
                    f"<b>{lab}</b><br>"
                    f"<b>VM : {val:,.1f} M€</b><br>"
                    f"<b>Part du total : {pct:.1%}</b>"
                )
                for lab, val, pct in zip(labels, vals, parts)
            ]

            _IMMO_PALETTE = [
                "#714A80", "#2C6FAC", "#3A9E5F", "#D4704B",
                "#8B6BB5", "#2A9BAB", "#B55C3A", "#C95B8B",
                "#4D8B7A", "#7B8B3A", "#5B7AB5", "#B58B3A",
            ]

            fig_pie = px.pie(
                df_graph_pie,
                names=dim_col,
                values="VM_MEUR",
                hole=0.55,
                color_discrete_sequence=_IMMO_PALETTE,
            )
            fig_pie.update_traces(
                texttemplate="<b>%{percent}</b>",
                textposition="inside",
                textfont=dict(size=12, color="white"),
                marker=dict(line=dict(width=1.5, color="white")),
                hovertext=hover_pie,
                hovertemplate="%{hovertext}<extra></extra>",
            )
            fig_pie.update_layout(
                autosize=True,
                height=550,
                margin=dict(l=40, r=40, t=20, b=160),
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.18,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=11),
                    tracegroupgap=4,
                ),
                annotations=[dict(
                    text=f"<b>{total:,.1f}</b><br>M€".replace(",", " ").replace(".", ","),
                    x=0.5, y=0.5,
                    font=dict(size=18, color="#333333"),
                    showarrow=False,
                )],
            )

    # On renvoie tout ce qu’il faut pour Streamlit ET pour le futur Rapport
    return pd.to_datetime(d0), pd.to_datetime(d1), label_dim, view, fig_pie


# ======================================================================
# 2) Fonction Streamlit : utilise le builder et gère l’affichage
# ======================================================================

_GESTION_MAP_IMMO   = {"1": "Mandats", "2": "Direct hors OPC", "3": "Fonds dédiés", "4": "Direct OPC"}
_GESTION_ORDER_IMMO = ["Mandats", "Direct hors OPC", "Fonds dédiés", "Direct OPC", "Autres"]


def _build_detail_immo_table(
    dff: pd.DataFrame,
    d0,
    d1,
    filtre_sous_classe: list,
    filtre_pays: list,
    filtre_type_gestion: list,
    search_lib: str,
    top_n: int,
):
    d0_date = pd.to_datetime(d0).date()
    d1_date = pd.to_datetime(d1).date()
    df1 = dff[dff["DATE_TRANSPA"] == d1_date].copy()
    df0 = dff[dff["DATE_TRANSPA"] == d0_date].copy()
    if df1.empty:
        return None

    # Type de gestion
    if "TYPE_GESTION_2" in df1.columns:
        df1["TYPE_GESTION_LIB"] = df1["TYPE_GESTION_2"].astype(str).map(_GESTION_MAP_IMMO).fillna("Autres")
    else:
        df1["TYPE_GESTION_LIB"] = "n.d."

    # VM numérique
    df1["VM_INIT"] = pd.to_numeric(df1["VM_INIT"], errors="coerce").fillna(0.0)
    df1 = df1[df1["VM_INIT"] > 0].copy()
    if df1.empty:
        return None

    sous_cl_col = "SOUS_CLASSIF_RF" if "SOUS_CLASSIF_RF" in df1.columns else None
    pays_col    = "PAYS"            if "PAYS"            in df1.columns else None
    libelle_col = "LIBELLE"         if "LIBELLE"         in df1.columns else None

    # Pré-filtrage
    if filtre_sous_classe and sous_cl_col:
        df1 = df1[df1[sous_cl_col].isin(filtre_sous_classe)]
    if filtre_pays and pays_col:
        df1 = df1[df1[pays_col].isin(filtre_pays)]
    if filtre_type_gestion:
        df1 = df1[df1["TYPE_GESTION_LIB"].isin(filtre_type_gestion)]
    if search_lib and libelle_col:
        df1 = df1[df1[libelle_col].astype(str).str.contains(search_lib, case=False, na=False)]
    if df1.empty:
        return None

    nb_total = len(df1)

    # VaR immo
    for c in ["VM_PMVL_IMMO_VAR95", "VM_PMVL_IMMO_VAR99"]:
        if c in df1.columns:
            df1[c] = pd.to_numeric(df1[c], errors="coerce").fillna(df1["VM_INIT"])
        else:
            df1[c] = df1["VM_INIT"]

    df1["VAR95_MEUR"] = (df1["VM_PMVL_IMMO_VAR95"] - df1["VM_INIT"]).abs() / 1e6
    df1["VAR99_MEUR"] = (df1["VM_PMVL_IMMO_VAR99"] - df1["VM_INIT"]).abs() / 1e6
    df1["VM_FIN_MEUR"] = df1["VM_INIT"] / 1e6

    # Variation d0→d1
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
    if pays_col:
        col_map[pays_col] = "Pays"; keep.append(pays_col)
    for c, lbl in [("VM_FIN_MEUR", "VM (M€)"), ("ALLOC", "Alloc (%)"),
                   ("Delta_VM", "Δ VM (M€)"), ("Delta_VM_pct", "Δ VM (%)"),
                   ("Tendance", "Tendance"),
                   ("VAR95_MEUR", "VaR 95% (M€)"), ("VAR99_MEUR", "VaR 99% (M€)")]:
        col_map[c] = lbl; keep.append(c)

    result = df1[keep].rename(columns=col_map)

    # Ligne TOTAL
    t_fin   = result["VM (M€)"].sum()
    t_delta = result["Δ VM (M€)"].sum()
    t_deb   = t_fin - t_delta
    t_pct   = (t_delta / t_deb * 100) if t_deb != 0 else np.nan
    total_row = {c: "" for c in result.columns}
    total_row[result.columns[0]] = "TOTAL"
    total_row["VM (M€)"]         = t_fin
    total_row["Alloc (%)"]       = result["Alloc (%)"].sum()
    total_row["Δ VM (M€)"]       = t_delta
    total_row["Δ VM (%)"]        = t_pct
    total_row["Tendance"]        = trend(t_delta / t_deb if t_deb != 0 else np.nan)
    total_row["VaR 95% (M€)"]    = result["VaR 95% (M€)"].sum()
    total_row["VaR 99% (M€)"]    = result["VaR 99% (M€)"].sum()
    result = pd.concat([result, pd.DataFrame([total_row])], ignore_index=True)

    return result, nb_total


def _render_detail_immo_section(dff: pd.DataFrame, d0, d1):
    d1_date = pd.to_datetime(d1).date()
    df_d1 = dff[dff["DATE_TRANSPA"] == d1_date].copy()
    if df_d1.empty:
        st.info("Aucune donnée disponible pour le détail par titre.")
        return

    if "TYPE_GESTION_2" in df_d1.columns:
        df_d1["TYPE_GESTION_LIB"] = df_d1["TYPE_GESTION_2"].astype(str).map(_GESTION_MAP_IMMO).fillna("Autres")
        types_gestion_dispo = [g for g in _GESTION_ORDER_IMMO if g in df_d1["TYPE_GESTION_LIB"].unique()]
    else:
        types_gestion_dispo = []

    sous_cl_col = "SOUS_CLASSIF_RF" if "SOUS_CLASSIF_RF" in df_d1.columns else None
    pays_col    = "PAYS"            if "PAYS"            in df_d1.columns else None

    sous_classes_dispo = sorted(df_d1[sous_cl_col].dropna().unique().tolist()) if sous_cl_col else []
    pays_dispo         = sorted(df_d1[pays_col].dropna().unique().tolist())    if pays_col    else []

    # Filtres
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        filtre_sous_classe = st.multiselect("Sous-classe d'actif", options=sous_classes_dispo, default=[], key="det_immo_sc")
    with fc2:
        filtre_pays = st.multiselect("Pays", options=pays_dispo, default=[], key="det_immo_pays")
    with fc3:
        filtre_type_gestion = st.multiselect("Type de gestion", options=types_gestion_dispo, default=[], key="det_immo_gestion")
    with fc4:
        top_n = st.selectbox(
            "Top N titres",
            options=[20, 50, 100, 0],
            format_func=lambda x: "Tous" if x == 0 else str(x),
            index=1,
            key="det_immo_topn",
        )

    search_lib = st.text_input("Libellé (recherche)", value="", key="det_immo_lib")

    result = _build_detail_immo_table(
        dff, d0, d1,
        filtre_sous_classe, filtre_pays, filtre_type_gestion,
        search_lib, top_n,
    )

    if result is None:
        st.info("Aucun titre ne correspond aux filtres sélectionnés.")
        return

    df_detail, nb_total = result
    nb_affiches = len(df_detail) - 1  # hors TOTAL

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

    excel_bytes = df_to_excel_bytes(df_detail, sheet_name="Risque_Immo_Titres")
    st.download_button(
        label="📥 Télécharger en Excel",
        data=excel_bytes,
        file_name="risque_immo_detail_titres.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="det_immo_excel",
    )


_CSS_TABLE_HEADER = """
<style>
div[data-testid="stDataFrame"] div[role="columnheader"] {
    background-color: #714A80 !important;
    color: white !important;
    font-weight: bold !important;
}
</style>
"""

def render_risque_immo_tab(df_selection: pd.DataFrame, date_debut, date_fin):
    st.markdown(_CSS_TABLE_HEADER, unsafe_allow_html=True)
    """
    Onglet Risque Immobilier :
    - filtre RSQ_FIN_IMMO == 1
    - Agrégation par Titre
    - Tableau: Top 10 + "Autres" + Total
    - Camembert : Top 10 + "Autres"
    """

    st.subheader("Risque Immobilier")

    build = build_risque_immo_section(df_selection, date_debut, date_fin)
    if build is None:
        st.info("Aucune donnée exploitable pour le Risque Immobilier sur la période sélectionnée.")
        return

    d0, d1, label_dim, view, fig_pie = build

    st.write(
        f"Période : **{d0.strftime('%d-%m-%Y')}** ⮕ "
        f"**{d1.strftime('%d-%m-%Y')}**"
    )

    # -------- Tableau + export Excel --------
    st.markdown("**Top 10 Titres**")
    col_table, col_graphs = st.columns([1.8, 1])

    with col_table:
        styled = apply_common_table_styles(view)

        render_static_dataframe(styled)

        excel_bytes = df_to_excel_bytes(view, sheet_name="Risque_Immobilier")
        st.download_button(
            label="📥Télécharger en Excel",
            data=excel_bytes,
            file_name="risque_immobilier.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # -------- Camembert --------
    with col_graphs:
        if fig_pie is None:
            st.info("Impossible de tracer le camembert : aucune VM positive.")
        else:
            st.plotly_chart(fig_pie, use_container_width=True, key="immo_pie_rapport", config={"displayModeBar": "hover"})

    # Stockage pour l'onglet Rapport
    st.session_state["rapport_immo"] = {
        "fig_pie": fig_pie,
        "table":   view,
    }

    # ======================================================
    # Détail par titre
    # ======================================================
    st.markdown("---")
    show_detail = st.toggle("Afficher le détail par titre", value=False, key="immo_detail_toggle")
    if show_detail:
        # Reconstruction de dff (même filtre que build_risque_immo_section)
        dff_det = df_selection.copy()
        dff_det = dff_det[dff_det["RSQ_FIN_IMMO"].astype(str) == "1"].copy()
        dff_det["DATE_TRANSPA"] = pd.to_datetime(dff_det["DATE_TRANSPA"]).dt.date
        _render_detail_immo_section(dff_det, d0, d1)