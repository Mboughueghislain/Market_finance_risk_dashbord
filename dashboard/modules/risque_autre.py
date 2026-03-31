# dashboard/modules/risque_autre.py

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px

from modules.format_utils import (
    trend,
    fmt_meur,
    fmt_delta_meur,
    fmt_pct,
    df_to_excel_bytes,
)


def render_risque_autre_tab(df_selection: pd.DataFrame, date_debut, date_fin):
    """
    Onglet Risque Autre :
    - filtre RSQ_FIN_AUTRE == 1 
    """

    st.subheader("Risque Autre")

    risk_col = "RSQ_FIN_AUTRE"  # adapte si tu as un autre flag
    if risk_col not in df_selection.columns:
        st.info(f"Colonne **{risk_col}** absente, impossible de calculer le risque Autre.")
        return

    choix_dim_affichage = st.radio(
        "Vue par :",
        options=["Type de groupe", "Type d'émetteur"],
        index=0,
        horizontal=True,
        key="autre_dim",
    )

    mapping_dim = {
        "Type de groupe": "TYPE_GROUPE",
        "Type d'émetteur": "TYPE_EMETTEUR",
    }
    dim_col = mapping_dim[choix_dim_affichage]

    if dim_col not in df_selection.columns:
        st.info(f"Colonne **{dim_col}** absente, impossible d'agréger par cette dimension.")
        return

    dff = df_selection.copy()
    dff = dff[dff[risk_col].astype(str) == "1"].copy()

    if dff.empty:
        st.info("Aucune ligne marquée RSQ_FIN_AUTRE = 1 avec les filtres actuels.")
        return

    dff[dim_col] = dff[dim_col].fillna("n.d.")

    if "DATE_TRANSPA" not in dff.columns:
        st.info("Colonne DATE_TRANSPA absente, impossible de calculer les variations.")
        return

    dff["DATE_TRANSPA"] = pd.to_datetime(dff["DATE_TRANSPA"]).dt.date
    d0 = dff.loc[dff["DATE_TRANSPA"] <= pd.to_datetime(date_debut).date(), "DATE_TRANSPA"].max()
    d1 = dff.loc[dff["DATE_TRANSPA"] <= pd.to_datetime(date_fin).date(), "DATE_TRANSPA"].max()

    if pd.isna(d0) or pd.isna(d1):
        st.info("Aucune date de transparisation valide pour la période sélectionnée.")
        return

    st.write(
        f"Période : **{pd.to_datetime(d0).strftime('%d-%m-%Y')}** ⮕ "
        f"**{pd.to_datetime(d1).strftime('%d-%m-%Y')}**"
    )

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

    res = pd.concat([debut, fin], axis=1).fillna(0).reset_index()
    res["Delta_VM"] = res["VM_FIN"] - res["VM_DEBUT"]
    res["Delta_VM_pct"] = np.where(
        res["VM_DEBUT"] != 0,
        res["Delta_VM"] / res["VM_DEBUT"],
        np.nan,
    )
    res["Tendance"] = res["Delta_VM_pct"].apply(trend)

    total_VM_debut = res["VM_DEBUT"].sum().round()
    total_VM_fin = res["VM_FIN"].sum().round()
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

    res = pd.concat([res, total_row], ignore_index=True)

    view = res.copy()
    for c in ["VM_DEBUT", "VM_FIN", "Delta_VM"]:
        view[c] = view[c] / 1e6
    view["Delta_VM_pct"] = view["Delta_VM_pct"] * 100

    view = view.rename(columns={
        dim_col: choix_dim_affichage,
        "VM_DEBUT": "Valeur de marché début (M€)",
        "VM_FIN": "Valeur de marché fin (M€)",
        "Delta_VM": "Δ VM (M€)",
        "Delta_VM_pct": "Δ VM (%)",
        "Tendance": "Tendance",
    })

    def style_total(row):
        if row[choix_dim_affichage] == "TOTAL":
            return ["background-color: #714A80; color: white; font-weight: bold"] * len(row)
        return [""] * len(row)

    styled = (
        view.style
        .format({
            "Valeur de marché début (M€)": fmt_meur,
            "Valeur de marché fin (M€)": fmt_meur,
            "Δ VM (M€)": fmt_delta_meur,
            "Δ VM (%)": fmt_pct,
        })
        .apply(style_total, axis=1)
    )

    col_table, col_graphs = st.columns([1.1, 1])

    with col_table:
        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            height=35 * (len(view) + 1) + 3,
        )

        excel_bytes = df_to_excel_bytes(view, sheet_name="Risque_Autre")
        st.download_button(
            label="📥Télécharger en Excel",
            data=excel_bytes,
            file_name="risque_autre.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_graphs:
        df_graph = res[res[dim_col] != "TOTAL"].copy()
        if not df_graph.empty:
            df_graph_pie = df_graph.copy()
            df_graph_pie["VM_MEUR"] = df_graph_pie["VM_FIN"] / 1e6
            total_pie = df_graph_pie["VM_MEUR"].sum()
            fig_pie = px.pie(
                df_graph_pie,
                names=dim_col,
                values="VM_MEUR",
                title="Répartition par " + choix_dim_affichage,
                hole=0.55,
            )
            fig_pie.update_layout(
                annotations=[dict(
                    text=f"<b>{total_pie:,.1f}</b><br>M€".replace(",", " ").replace(".", ","),
                    x=0.5, y=0.5,
                    font=dict(size=18, color="#333333"),
                    showarrow=False,
                )],
            )
            st.plotly_chart(fig_pie, use_container_width=True)

            df_graph_bar = df_graph.copy()
            df_graph_bar["Delta_VM_MEUR"] = df_graph_bar["Delta_VM"] / 1e6
            fig_bar = px.bar(
                df_graph_bar,
                x="Delta_VM_MEUR",
                y=dim_col,
                orientation="h",
                title="Variation de la VM (M€)",
                labels={"Delta_VM_MEUR": "Δ VM (M€)", dim_col: ""},
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("Pas de données pour tracer les graphes Autre.")