import streamlit as st
import pandas as pd
import plotly.io as pio
from typing import Optional

try:
    pio.defaults.mathjax = None  # désactive MathJax → export PNG plus rapide
except Exception:
    pass

from modules.format_utils import (
    fmt_meur,
    fmt_delta_meur,
    fmt_pct,
    fmt_bp,
    apply_common_table_styles,
)
from modules.rapport_pdf_V2 import build_full_pdf_report_v2


# =====================================================================
# Fonction principale : onglet "Rapport commenté"
# Les figures et tableaux viennent du session_state alimenté par
# chaque onglet spécifique (portefeuille, taux, spread, action, immo).
# =====================================================================
def build_portefeuille_block_for_report(df_selection, use_transpa, date_debut, date_fin):

    sections_for_export = []

    periode_label = (
        f"{pd.to_datetime(date_debut).strftime('%d/%m/%Y')} "
        f"→ {pd.to_datetime(date_fin).strftime('%d/%m/%Y')}"
    )

    # =================================================================
    # 1. PORTEFEUILLE GLOBAL
    # =================================================================
    st.markdown("## 1. Portefeuille global")

    pf = st.session_state.get("rapport_portefeuille")
    if not pf:
        st.info("Données non disponibles — visitez l'onglet Portefeuille.")
    else:
        fig_pie   = pf.get("fig_pie")
        fig_bar   = pf.get("fig_bar")
        table_pf  = pf.get("table")

        col_pie, col_bar = st.columns(2)
        if fig_pie:
            col_pie.plotly_chart(fig_pie, use_container_width=True, key="rapport_pf_pie")
        if fig_bar:
            col_bar.plotly_chart(fig_bar, use_container_width=True, key="rapport_pf_bar")

        if table_pf is not None and not table_pf.empty:
            st.dataframe(
                apply_common_table_styles(table_pf),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_pf) + 1) + 3,
            )

        commentaire_pf = st.text_area(
            "📝 Commentaire – Portefeuille",
            placeholder="Ex : hausse de la VM actions, stabilité du monétaire...",
            key="commentaire_portefeuille_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "portefeuille",
            "title": "1. Portefeuille global",
            "subtitle": "Répartition de la valeur de marché par classe d'actifs",
            "table": table_pf,
            "_figures_raw": [fig_pie, fig_bar],
            "comment": commentaire_pf,
        })

    # =================================================================
    # 2. RISQUE TAUX
    # =================================================================
    st.markdown("---")
    st.markdown("## 2. Risque Taux")

    sections_for_export.append({"is_section_header": True, "title": "2. Risque Taux"})

    taux = st.session_state.get("rapport_taux")
    if not taux:
        st.info("Données non disponibles — visitez l'onglet Risque Taux.")
    else:
        cols_gestion   = taux.get("cols_gestion", [])
        fig_stack      = taux.get("fig_stack")
        table_duration = taux.get("table_duration")
        fig_var_seg    = taux.get("fig_var_seg")
        table_var      = taux.get("table_var")

        # 2.1 Duration x type de gestion
        st.markdown("### 2.1 Répartition par duration et type de gestion")
        if fig_stack:
            st.plotly_chart(fig_stack, use_container_width=True, key="rapport_taux_stack")
        if table_duration is not None and not table_duration.empty:
            fmt_dur = {c: fmt_meur for c in cols_gestion + ["Total"] if c in table_duration.columns}
            st.dataframe(
                apply_common_table_styles(table_duration, fmt_dur),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_duration) + 1) + 3,
            )
        commentaire_taux_vm = st.text_area(
            "📝 Commentaire – Répartition Taux (duration / gestion)",
            key="commentaire_taux_vm_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "taux_duration",
            "title": "2.1 Risque Taux – Répartition par duration et type de gestion",
            "subtitle": "",
            "table": table_duration,
            "_figures_raw": [fig_stack],
            "comment": commentaire_taux_vm,
        })

        # 2.2 Variation & VaR
        st.markdown("---")
        st.markdown("### 2.2 Variation & VaR par segment de duration")
        if fig_var_seg:
            st.plotly_chart(fig_var_seg, use_container_width=True, key="rapport_taux_var")
        if table_var is not None and not table_var.empty:
            fmt_var = {
                "Δ VM (M€)":    fmt_meur,
                "VaR 95% (M€)": fmt_meur,
                "VaR 99% (M€)": fmt_meur,
            }
            st.dataframe(
                apply_common_table_styles(table_var, fmt_var),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_var) + 1) + 3,
            )
        commentaire_taux_var = st.text_area(
            "📝 Commentaire – Variation & VaR Taux",
            key="commentaire_taux_var_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "taux_var",
            "title": "2.2 Risque Taux – Variation & VaR par segment de duration",
            "subtitle": "",
            "table": table_var,
            "_figures_raw": [fig_var_seg],
            "comment": commentaire_taux_var,
        })

    # =================================================================
    # 3. RISQUE DE SPREAD
    # =================================================================
    st.markdown("---")
    st.markdown("## 3. Risque de Spread")

    sections_for_export.append({"is_section_header": True, "title": "3. Risque de Spread"})

    spread = st.session_state.get("rapport_spread")
    if not spread:
        st.info("Données non disponibles — visitez l'onglet Risque Spread.")
    else:
        # 3.1 Vue globale
        st.markdown("### 3.1 Vue globale")
        fig_scatter  = spread.get("fig_scatter")
        fig_treemap  = spread.get("fig_treemap")
        table_global = spread.get("table_global")

        if fig_scatter:
            st.plotly_chart(fig_scatter, use_container_width=True, key="rapport_spread_scatter")
        if table_global is not None and not table_global.empty:
            st.dataframe(
                apply_common_table_styles(table_global),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_global) + 1) + 3,
            )
        if fig_treemap:
            st.markdown("**Répartition par Type d'émetteur / Rating / Titre**")
            st.plotly_chart(fig_treemap, use_container_width=True, key="rapport_spread_treemap")
        commentaire_spread_global = st.text_area(
            "📝 Commentaire – Risque de Spread global",
            key="commentaire_spread_global_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "spread_global",
            "title": "3.1 Risque de Spread – Vue globale",
            "subtitle": "",
            "table": table_global,
            "_figures_raw": [fig_scatter, fig_treemap],
            "comment": commentaire_spread_global,
        })

        # 3.2 Souverain
        st.markdown("---")
        st.markdown("### 3.2 Spread Souverain")
        fig_geo     = spread.get("fig_geo")
        table_souv  = spread.get("table_souverain")

        if fig_geo:
            st.plotly_chart(fig_geo, use_container_width=True, key="rapport_spread_geo")
        if table_souv is not None and not table_souv.empty:
            st.dataframe(
                apply_common_table_styles(table_souv),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_souv) + 1) + 3,
            )
        commentaire_souv = st.text_area(
            "📝 Commentaire – Spread souverain",
            key="commentaire_spread_souverain_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "spread_souverain",
            "title": "3.2 Risque de Spread – Souverain",
            "subtitle": "",
            "table": table_souv,
            "_figures_raw": [fig_geo],
            "comment": commentaire_souv,
        })

        # 3.3 Corporate
        st.markdown("---")
        st.markdown("### 3.3 Spread Corporate")
        fig_conc   = spread.get("fig_conc")
        table_corp = spread.get("table_corporate")

        if fig_conc:
            st.plotly_chart(fig_conc, use_container_width=True, key="rapport_spread_conc")
        if table_corp is not None and not table_corp.empty:
            st.dataframe(
                apply_common_table_styles(table_corp),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_corp) + 1) + 3,
            )
        commentaire_corp = st.text_area(
            "📝 Commentaire – Spread Corporate",
            key="commentaire_spread_corporate_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "spread_corporate",
            "title": "3.3 Risque de Spread – Corporate",
            "subtitle": "",
            "table": table_corp,
            "_figures_raw": [fig_conc],
            "comment": commentaire_corp,
        })

    # =================================================================
    # 4. RISQUE ACTION
    # =================================================================
    st.markdown("---")
    st.markdown("## 4. Risque Action")

    sections_for_export.append({"is_section_header": True, "title": "4. Risque Action"})

    action = st.session_state.get("rapport_action")
    if not action:
        st.info("Données non disponibles — visitez l'onglet Risque Action.")
    else:
        # 4.1 Concentration par émetteur / groupe
        st.markdown("### 4.1 Concentration par émetteur / groupe")
        fig_issuer   = action.get("fig_issuer")
        table_issuer = action.get("table_issuer")

        if fig_issuer:
            st.plotly_chart(fig_issuer, use_container_width=True, key="rapport_action_issuer")
        if table_issuer is not None and not table_issuer.empty:
            st.dataframe(
                apply_common_table_styles(table_issuer),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_issuer) + 1) + 3,
            )
        commentaire_issuer = st.text_area(
            "📝 Commentaire – Concentration par émetteur / groupe",
            key="commentaire_action_issuer_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "action_emetteur",
            "title": "4.1 Risque Action – Concentration par émetteur / groupe",
            "subtitle": "",
            "table": table_issuer,
            "_figures_raw": [fig_issuer],
            "comment": commentaire_issuer,
        })

        # 4.2 Concentration géographique
        st.markdown("---")
        st.markdown("### 4.2 Concentration géographique")
        fig_geo_action = action.get("fig_geo")
        table_geo      = action.get("table_geo")

        if fig_geo_action:
            st.plotly_chart(fig_geo_action, use_container_width=True, key="rapport_action_geo")
        if table_geo is not None and not table_geo.empty:
            st.dataframe(
                apply_common_table_styles(table_geo),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_geo) + 1) + 3,
            )
        commentaire_geo = st.text_area(
            "📝 Commentaire – Concentration géographique (Action)",
            key="commentaire_action_geo_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "action_geo",
            "title": "4.2 Risque Action – Concentration géographique",
            "subtitle": "",
            "table": table_geo,
            "_figures_raw": [fig_geo_action],
            "comment": commentaire_geo,
        })

        # 4.3 Concentration par secteur
        st.markdown("---")
        st.markdown("### 4.3 Concentration par secteur")
        fig_secteur  = action.get("fig_secteur")
        table_secteur = action.get("table_secteur")

        if fig_secteur:
            st.plotly_chart(fig_secteur, use_container_width=True, key="rapport_action_secteur")
        if table_secteur is not None and not table_secteur.empty:
            st.dataframe(
                apply_common_table_styles(table_secteur),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_secteur) + 1) + 3,
            )
        commentaire_sect = st.text_area(
            "📝 Commentaire – Concentration par secteur (Action)",
            key="commentaire_action_secteur_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "action_secteur",
            "title": "4.3 Risque Action – Concentration par secteur",
            "subtitle": "",
            "table": table_secteur,
            "_figures_raw": [fig_secteur],
            "comment": commentaire_sect,
        })

    # =================================================================
    # 5. RISQUE IMMOBILIER
    # =================================================================
    st.markdown("---")
    st.markdown("## 5. Risque Immobilier")

    immo = st.session_state.get("rapport_immo")
    if not immo:
        st.info("Données non disponibles — visitez l'onglet Risque Immobilier.")
    else:
        fig_immo   = immo.get("fig_pie")
        table_immo = immo.get("table")

        if fig_immo:
            st.plotly_chart(fig_immo, use_container_width=True, key="rapport_immo_pie")
        if table_immo is not None and not table_immo.empty:
            st.dataframe(
                apply_common_table_styles(table_immo),
                use_container_width=True,
                hide_index=True,
                height=35 * (len(table_immo) + 1) + 3,
            )
        commentaire_immo = st.text_area(
            "📝 Commentaire – Risque Immobilier",
            key="commentaire_immo_rapport",
            height=120,
        )
        sections_for_export.append({
            "id": "immobilier",
            "title": "5. Risque Immobilier",
            "subtitle": "",
            "table": table_immo,
            "_figures_raw": [fig_immo],
            "comment": commentaire_immo,
        })

    # =================================================================
    # 6. EXPORT PDF
    # =================================================================
    st.markdown("---")
    st.markdown("## Export du rapport complet")

    if not sections_for_export:
        st.info("Aucune section disponible pour l'export.")
        return

    if st.button("📄 Générer le PDF complet", key="btn_build_pdf"):
        with st.spinner("Génération du rapport PDF..."):
            from modules.rapport_export import fig_to_png_bytes
            for sec in sections_for_export:
                figs_raw = sec.pop("_figures_raw", []) or []
                sec["figures_png"] = [
                    fig_to_png_bytes(fig) if fig is not None else None
                    for fig in figs_raw
                ]
            pdf_bytes = build_full_pdf_report_v2(sections_for_export, periode_label)

        st.download_button(
            "Télécharger le rapport (PDF)",
            data=pdf_bytes,
            file_name="rapport_risque_commente.pdf",
            mime="application/pdf",
            key="btn_download_pdf",
        )
