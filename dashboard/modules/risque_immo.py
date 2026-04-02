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