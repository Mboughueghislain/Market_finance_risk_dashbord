# dashboard/modules/portefeuille.py

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from typing import Optional
from modules.format_utils import (
    fmt_fr,
    trend,
    fmt_meur,
    fmt_delta_meur,
    fmt_pct,
    df_to_excel_bytes,
    apply_common_table_styles,
    add_alloc_columns,
)

def compute_portefeuille_metrics(
    dff: pd.DataFrame,
    use_transpa: bool,
    date_debut,
    date_fin,
    group_col: str = "CLASSIF_RF",
    class_col: Optional[str] = None,
    extra_dim_cols: list = None,
):
    """
    Prépare toutes les données nécessaires pour l'onglet Portefeuille :
      - df_cat : VM par groupe (classe ou sous-classe) pour la date de fin
      - view  : tableau agrégé avec VM début / fin, delta, tendance...
      - d0, d1 : dates effectives utilisées
      - has_VNC : booléen, indique si les colonnes VNC_* existent

    group_col : nom de la colonne utilisée pour l'agrégation principale
                (ex: "CLASSIF_RF" ou "SOUS_CLASSIF_RF")
    class_col : colonne "parent" (ex: "CLASSIF_RF" quand on groupe par sous-classe)
                utilisée uniquement pour le tableau.
    """
    dff = dff.copy()

    has_VNC = (not use_transpa) and ("VNC" in dff.columns)

    # Dates en type date
    dff["DATE_TRANSPA"] = pd.to_datetime(dff["DATE_TRANSPA"]).dt.date

    date_debut = pd.to_datetime(date_debut).date()
    date_fin = pd.to_datetime(date_fin).date()

    d0 = dff.loc[dff["DATE_TRANSPA"] <= date_debut, "DATE_TRANSPA"].max()
    d1 = dff.loc[dff["DATE_TRANSPA"] <= date_fin, "DATE_TRANSPA"].max()

    if pd.isna(d0) or pd.isna(d1):
        return None, None, None, None, has_VNC

    # Colonne de groupement principale
    if group_col not in dff.columns:
        dff[group_col] = "Non classé"

    # Colonne parent optionnelle (classe quand group_col = sous-classe)
    if class_col is not None and class_col not in dff.columns:
        dff[class_col] = "Non classé"

    # Colonnes de groupement pour les agrégations
    grp = [group_col]
    if class_col is not None and class_col != group_col:
        grp = [class_col, group_col]
    # Colonnes supplémentaires (ex: ID, LIBELLE)
    if extra_dim_cols:
        grp = grp + [c for c in extra_dim_cols if c in dff.columns]

    # ------------ Répartition par groupe à la date de fin ------------
    df_cat = (
        dff[dff["DATE_TRANSPA"] == d1]
        .groupby(group_col, as_index=False)["VM_INIT"]
        .sum()
    )
    df_cat["VM_INIT"] = df_cat["VM_INIT"] / 1e6  # en M€

    # ------------ Agrégations début / fin ------------
    debut = (
        dff[dff["DATE_TRANSPA"] == d0]
        .groupby(grp, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_DEBUT")
    )
    fin = (
        dff[dff["DATE_TRANSPA"] == d1]
        .groupby(grp, dropna=False)["VM_INIT"]
        .sum()
        .rename("VM_FIN")
    )

    if has_VNC:
        debut_VNC = (
            dff[dff["DATE_TRANSPA"] == d0]
            .groupby(grp, dropna=False)["VNC"]
            .sum()
            .rename("VNC_DEBUT")
        )
        fin_VNC = (
            dff[dff["DATE_TRANSPA"] == d1]
            .groupby(grp, dropna=False)["VNC"]
            .sum()
            .rename("VNC_FIN")
        )
        res = pd.concat([debut, fin, debut_VNC, fin_VNC], axis=1).fillna(0).reset_index()
    else:
        res = pd.concat([debut, fin], axis=1).fillna(0).reset_index()

    # Deltas
    res["Delta_VM"] = res["VM_FIN"] - res["VM_DEBUT"]
    res["Delta_VM_pct"] = np.where(
        res["VM_DEBUT"] != 0,
        res["Delta_VM"] / res["VM_DEBUT"],
        np.nan,
    )

    if has_VNC:
        res["Delta_VNC"] = res["VNC_FIN"] - res["VNC_DEBUT"]
        res["Delta_VNC_pct"] = np.where(
            res["VM_DEBUT"] != 0,
            res["Delta_VNC"] / res["VM_DEBUT"],
            np.nan,
        )
        res["effet_marche"] = res["Delta_VM_pct"] - res["Delta_VNC_pct"]

    res["Tendance"] = res["Delta_VM_pct"].apply(trend)

    # ------------ Ligne TOTAL ------------
    total_VM_debut = res["VM_DEBUT"].sum().round()
    total_VM_fin = res["VM_FIN"].sum().round()
    total_VM_delta = res["Delta_VM"].sum().round()
    total_VM_pct = (
        total_VM_delta / total_VM_debut if total_VM_debut != 0 else np.nan
    )

    if class_col is not None and class_col != group_col:
        # Mode sous-classe :
        # TOTAL seulement dans la colonne Classe
        total_row = {
            class_col: "TOTAL",
            group_col: "",   # vide la sous-classe
            "VM_DEBUT": total_VM_debut,
            "VM_FIN": total_VM_fin,
            "Delta_VM": total_VM_delta,
            "Delta_VM_pct": total_VM_pct,
            "Tendance": trend(total_VM_pct),
        }
        # Colonnes extra vides sur la ligne TOTAL
        if extra_dim_cols:
            for c in extra_dim_cols:
                if c in dff.columns:
                    total_row[c] = ""
    else:
        # Mode classe simple
        total_row = {
            group_col: "TOTAL",
            "VM_DEBUT": total_VM_debut,
            "VM_FIN": total_VM_fin,
            "Delta_VM": total_VM_delta,
            "Delta_VM_pct": total_VM_pct,
            "Tendance": trend(total_VM_pct),
        }
    if has_VNC:
        total_VNC_debut = res["VNC_DEBUT"].sum().round()
        total_VNC_fin = res["VNC_FIN"].sum().round()
        total_VNC_delta = res["Delta_VNC"].sum().round()
        total_VNC_delta_pct = (
            total_VNC_delta / total_VM_debut if total_VM_debut != 0 else np.nan
        )
        total_effet_marche = (
            total_VM_pct - total_VNC_delta_pct
            if pd.notna(total_VM_pct) and pd.notna(total_VNC_delta_pct)
            else np.nan
        )
        total_row.update(
            {
                "VNC_DEBUT": total_VNC_debut,
                "VNC_FIN": total_VNC_fin,
                "Delta_VNC": total_VNC_delta,
                "Delta_VNC_pct": total_VNC_delta_pct,
                "effet_marche": total_effet_marche,
            }
        )

    total_row = pd.DataFrame([total_row])

    # ------------ Tri pour l'affichage ------------
    if class_col is not None and class_col in res.columns and class_col != group_col:
        # 1) On calcule l'ordre des classes en fonction de leur VM totale
        ordre_classes = (
            res.groupby(class_col)["VM_FIN"]
            .sum()
            .sort_values(ascending=False)
            .index
            .tolist()
        )

        # 2) On impose cet ordre à la colonne de classe
        res[class_col] = pd.Categorical(
            res[class_col],
            categories=ordre_classes,
            ordered=True,
        )

        # 3) On trie d'abord par classe (dans l'ordre ci-dessus), puis par VM_FIN décroissante
        res_sorted = res.sort_values(
            by=[class_col, "VM_FIN"], ascending=[True, False]
        )
    else:
        # Cas "vue Classe" classique : tri par VM_FIN décroissante
        res_sorted = res.sort_values("VM_FIN", ascending=False)

    # On ajoute la ligne TOTAL à la fin
    res = pd.concat([res_sorted, total_row], ignore_index=True)

    # ------------ Vue pour affichage ------------
    view = res.copy()

    for c in ["VM_DEBUT", "VM_FIN", "Delta_VM"]:
        if c in view.columns:
            view[c] = view[c] / 1e6  # M€

    if "Delta_VM_pct" in view.columns:
        view["Delta_VM_pct"] = view["Delta_VM_pct"] * 100

    view = add_alloc_columns(view, vm_fin_col="VM_FIN", delta_vm_col="Delta_VM")

    if has_VNC:
        for c in ["VNC_DEBUT", "VNC_FIN", "Delta_VNC"]:
            if c in view.columns:
                view[c] = view[c] / 1e6
        for c in ["Delta_VNC_pct", "effet_marche"]:
            if c in view.columns:
                view[c] = view[c] * 100

    return df_cat, view, d0, d1, has_VNC

def build_portefeuille_figures(
    df_cat: pd.DataFrame,
    view: pd.DataFrame,
    group_col: str = "CLASSIF_RF",
    dim_label: str = "Classe d'actifs",
):
    """
    Construit les deux graphiques du portefeuille (camembert + barres)
    sans appel à Streamlit.
    Retourne (fig_pie, fig_bar).

    group_col : colonne de regroupement (classe ou sous-classe)
    dim_label : libellé lisible pour les titres/axes
    """

    color_map = {
        "Obligation": "#1f77b4",
        "Monétaire": "#ff7f0e",
        "Immobilier": "#2ca02c",
        "Action": "#d62728",
        "Diversification": "#9467bd",
        "OPCVM Diversifié": "#8c564b",
        "IFT": "#7D7E83",
        "TOTAL": "#714A80",
    }

    # =======================
    # Pie chart
    # =======================
    fig_pie = None

    labels = df_cat[group_col].astype(str).tolist()
    vals = df_cat["VM_INIT"].astype(float).to_numpy()

    total_val = float(np.nansum(vals)) if len(vals) else 0.0
    if total_val > 0:
        parts = np.where(
            total_val != 0,
            vals / total_val * 100.0,
            0.0,
        )

        custom_vals = []
        for v in vals:
            try:
                custom_vals.append(fmt_fr(v, " M€"))
            except Exception:
                custom_vals.append("")

        custom_part = []
        for p in parts:
            try:
                custom_part.append(fmt_fr(p, " %"))
            except Exception:
                custom_part.append("")

        text_pie = [
            f"{lab}: {val}<br>{pct}"
            for lab, val, pct in zip(labels, custom_vals, custom_part)
        ]
        hover_pie = [
            f"{lab}<br>Valeur : {val}<br>Part : {pct}"
            for lab, val, pct in zip(labels, custom_vals, custom_part)]

        fig_pie = px.pie(
            df_cat,
            names=group_col,
            values="VM_INIT",
            title=f"Répartition de la Valeur de Marché par {dim_label}",
            hole=0.55,
            color=group_col,
            color_discrete_map=color_map,
        )
        fig_pie.update_traces(
            texttemplate="<b>%{percent:.1%}",
            textinfo="text",
            textposition="inside",
            hovertext=hover_pie,
            hovertemplate="<b>%{hovertext}</b><extra></extra>",
        )

    # =======================
    # Bar chart
    # =======================
    fig_bar = None

    # Exclure TOTAL + valeurs vides (barre grise)
    view_sans_total = view[
        view[group_col].notna() & (view[group_col] != "") & (view[group_col] != "TOTAL")
    ]

    if not view_sans_total.empty:
        # On prend aussi Delta_VM_pct pour calculer stable/hausse/baisse
        df_bar = view_sans_total[[group_col, "Delta_VM", "Delta_VM_pct"]].copy()

        SEUIL_STABLE_PCT = 0.5  # 0,5% (cohérent avec trend(seuil_pct=0.005))

        # Stable si |Δ VM (%)| < 0,5%
        df_bar["Signe"] = np.where(
            df_bar["Delta_VM_pct"].abs() < SEUIL_STABLE_PCT,
            "Stable",
            np.where(df_bar["Delta_VM_pct"] >= 0, "Hausse", "Baisse"),
        )

        fig_bar = px.bar(
            df_bar,
            x="Delta_VM",
            y=group_col,
            color="Signe",
            orientation="h",
            title=f"Variation de la Valeur de Marché par {dim_label} (M€)",
            labels={"Delta_VM": "", group_col: ""},
            category_orders={group_col: df_bar[group_col].tolist()},  # garde ton ordre
            color_discrete_map={"Hausse": "#2ca02c", "Baisse": "#d62728", "Stable": "#bcbd22"},
        )

        fig_bar.add_vline(x=0, line_width=1)

        fig_bar.update_traces(
            texttemplate="<b>%{x:,.1f} M€</b>",
            textposition="outside",
            cliponaxis=False,
            # hover plus riche (optionnel)
            hovertemplate="<b>%{y}</b><br><b>Δ VM : %{x:,.2f} M€</b><br><b>Δ VM (%) : %{customdata[0]:.2f}%</b><extra></extra>",
            customdata=df_bar[["Delta_VM_pct"]].to_numpy(),
        )

        fig_bar.update_layout(
            xaxis_title="",
            xaxis_tickformat=",.0f",
            showlegend=True,   # tu peux remettre False si tu ne veux pas la légende
            xaxis_showgrid=True,
            yaxis_showgrid=True,
            title_x=0.2,
        )

        min_delta = df_bar["Delta_VM"].min()
        max_delta = df_bar["Delta_VM"].max()
        lim = max(abs(min_delta), abs(max_delta)) if not df_bar.empty else 0
        if lim > 0:
            pad_left= 1.30
            pad_right = 1.25
            fig_bar.update_xaxes(range=[-lim * pad_left, lim * pad_right])
            
            fig_bar.update_layout(
                margin=dict(l=140, r=90, t=60, b=40)
            )

    return fig_pie, fig_bar

# Tri pour les sous-classes
ORDER_CLASSES = [
    "Obligation",
    "OPCVM Diversifié",
    "Action",
    "Immobilier",
    "Diversification",
    "Monétaire",
    "IFT",
]

ORDER_SUB = [
    "Souverain Taux Fixe",
    "Souverain indexé",
    "Corporate Taux Fixe",
    "Covered",
    "Subordonné",
    "OPCVM Taux",
    "OPCVM Taux Indexé",
    "OPCVM Convertible",
    "OPCVM Diversifié",
    "Action",
    "OPCVM Action",
    "OPCVM Monétaire",
    "Monétaire",
    "Pierre Papier",
    "Immobilier Physique",
    "Infrastructure",
    "Fonds de dettes",
    "Capital investissement"
]

# Fonction de tri pour le PDF : on trie d'abord par classe (ordre défini), puis par sous-classe (ordre défini)
def sort_portefeuille_pdf(df):

    class_col = "Classe d'actifs"
    sub_col = "Sous-classe d'actifs"

    df = df.copy()

    if class_col in df.columns:
        df[class_col] = pd.Categorical(
            df[class_col],
            categories=ORDER_CLASSES,
            ordered=True
        )

    if sub_col in df.columns:
        df[sub_col] = pd.Categorical(
            df[sub_col],
            categories=ORDER_SUB,
            ordered=True
        )

    sort_cols = [c for c in [class_col, sub_col] if c in df.columns]

    if sort_cols:
        df = df.sort_values(sort_cols)

    return df

# Fonction pour compresser les labels de groupe dans le tableau
def compress_group_labels(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    Affiche la valeur de group_col uniquement sur la 1ère ligne de chaque bloc,
    puis met vide sur les lignes suivantes (effet 'grouped' type PDF).
    """
    if group_col not in df.columns:
        return df

    out = df.copy()
    mask_dup = out[group_col].eq(out[group_col].shift(1))
    out.loc[mask_dup, group_col] = ""   # ou None
    return out

def render_portefeuille_tab(df_selection: pd.DataFrame, use_transpa: bool, date_debut, date_fin):
    """
    Fonction appelée depuis home.py pour afficher tout le bloc Portefeuille :
      - Filtres (classe / sous-classe d'actifs)
      - Graphs (pie + bar)
      - Tableau
      - Export Excel
    """
    st.subheader("Portefeuille")

    # ======================================================
    # ZONE FILTRES (en haut à gauche)
    # ======================================================
    CLASS_COL = "CLASSIF_RF"
    SUBCLASS_COL = "SOUS_CLASSIF_RF"  

    df_selection = df_selection.copy()

    # Sécurité : si les colonnes n'existent pas, on crée quelque chose de neutre
    if CLASS_COL not in df_selection.columns:
        df_selection[CLASS_COL] = "Non classé"
    if SUBCLASS_COL not in df_selection.columns:
        df_selection[SUBCLASS_COL] = "Non renseigné"

    # On récupère toutes les valeurs possibles de classe d'actifs
    all_classes = (
        df_selection[CLASS_COL]
        .dropna()
        .astype(str)
        .sort_values()
        .unique()
        .tolist()
    )

    # Options du filtre type de taux (calculées sur df_selection entier)
    _TYPES_TAUX_OPTIONS = ["Indexé inflation", "Taux fixe", "Autres"]

    with st.container():
        col_class, col_sous_class, col_taux, col_niveau = st.columns([1.4, 1.4, 1.2, 1])

        # ----- Multiselect Classe d'actifs -----
        with col_class:
            selected_classes = st.multiselect(
                "Classe d'actifs",
                options=all_classes,
                default=all_classes,  # par défaut : toutes sélectionnées
                placeholder="Choisissez les classes d'actifs"
            )

        # On restreint les sous-classes aux classes sélectionnées (si filtrées)
        if selected_classes:
            df_for_sous = df_selection[df_selection[CLASS_COL].isin(selected_classes)]
        else:
            df_for_sous = df_selection

        all_sous_classes = (
            df_for_sous[SUBCLASS_COL]
            .dropna()
            .astype(str)
            .sort_values()
            .unique()
            .tolist()
        )

        # ----- Multiselect Sous-classe d'actifs -----
        with col_sous_class:
            selected_sous_classes = st.multiselect(
                "Sous-classe d'actifs",
                options=all_sous_classes,
                default=[],
                placeholder="Choisissez les sous-classes d'actifs"
            )

        # ----- Multiselect Type de taux -----
        with col_taux:
            selected_types_taux = st.multiselect(
                "Type de taux",
                options=_TYPES_TAUX_OPTIONS,
                default=_TYPES_TAUX_OPTIONS,
                placeholder="Choisissez un type de taux"
            )

        # ----- Niveau d'analyse -----
        # Si l'utilisateur a sélectionné des sous-classes, on met par défaut "Sous-classe"
        default_index = 1 if selected_sous_classes else 0
        with col_niveau:
            niveau_analyse = st.radio(
                "Niveau d'analyse",
                options=["Classe d'actifs", "Sous-classe d'actifs"],
                index=default_index,
            )

    # On prépare un DataFrame filtré selon les choix utilisateur
    df_filtre = df_selection.copy()

    if selected_types_taux:
        has_cpn = "CPN_TYPE"    in df_filtre.columns
        has_idx = "INDIC_INDEX" in df_filtre.columns
        if has_cpn:
            cpn  = df_filtre["CPN_TYPE"].astype(str).str.strip()
            idx  = df_filtre["INDIC_INDEX"].astype(str).str.strip() if has_idx else None
            mask = pd.Series(False, index=df_filtre.index)
            if "Indexé inflation" in selected_types_taux and has_idx:
                mask |= (cpn == "FIXE") & (idx.isin(["True", "true", "1", "Y", "O"]))
            if "Taux fixe" in selected_types_taux and has_idx:
                mask |= (cpn == "FIXE") & (idx.isin(["False", "false", "0", "N"]))
            if "Autres" in selected_types_taux:
                mask |= (cpn != "FIXE")
            df_filtre = df_filtre[mask]

    if selected_classes:
        df_filtre = df_filtre[df_filtre[CLASS_COL].isin(selected_classes)]

    if selected_sous_classes:
        df_filtre = df_filtre[df_filtre[SUBCLASS_COL].isin(selected_sous_classes)]

    # ======================================================
    # CALCUL DES METRIQUES
    # ======================================================

    if niveau_analyse == "Sous-classe d'actifs":
        group_col = SUBCLASS_COL
        dim_label = "Sous-classe d'actifs"
        class_col = CLASS_COL          # on garde aussi la classe d'actifs
    else:
        group_col = CLASS_COL
        dim_label = "Classe d'actifs"
        class_col = None               # pas de colonne parent

    df_cat, view, d0, d1, has_VNC = compute_portefeuille_metrics(
        df_filtre,
        use_transpa,
        date_debut,
        date_fin,
        group_col=group_col,
        class_col=class_col,
    )

    if df_cat is None or view is None:
        st.warning("Aucune donnée disponible pour les filtres et dates sélectionnés.")
        return


    # ======================================================
    # GRAPHIQUES
    # ======================================================
    st.write(
        f"Période : **{pd.to_datetime(d0).strftime('%d-%m-%Y')}** ⮕ "
        f"**{pd.to_datetime(d1).strftime('%d-%m-%Y')}**"
    )
    col_pie, col_bar = st.columns([1, 1.2])

    # On construit les figures via la fonction réutilisable
    fig_pie, fig_bar = build_portefeuille_figures(df_cat, view, group_col=group_col, dim_label=dim_label)

    with col_pie:
        st.markdown(f"### Répartition par {dim_label.lower()}")
        if fig_pie is None:
            st.info("Impossible de tracer le graphique : toutes les VM sont nulles.")
        else:
            # Mise en forme du camembert
            total_meur = float(df_cat["VM_INIT"].sum())
            total_txt = f"{total_meur:,.1f}".replace(",", " ").replace(".", ",")
            fig_pie.update_layout(
                autosize=True,
                height=400,  # Hauteur totale de la figure
                margin=dict(
                    l=40,
                    r=40,  # marge à droite pour laisser respirer la légende
                    t=80,
                    b=80,
                ),
                legend=dict(
                    orientation="h",    # vertical
                    yanchor="top",
                    y=-0.1,
                    xanchor="center",    # le texte part vers la gauche
                    x=0.5,             # collé à droite, mais sans dépasser
                    font=dict(size=11),
                ),
                annotations=[dict(
                    text=f"<b>{total_txt}</b><br>M€",
                    x=0.5, y=0.5,
                    font=dict(size=18, color="#333333"),
                    showarrow=False,
                )],
            )

            st.plotly_chart(
                fig_pie,
                key="pf_pie_portefeuille"
            )

    with col_bar:
        st.markdown(f"### Variation de la valeur de marché par {dim_label.lower()}")
        if fig_bar is None:
            st.info("Pas assez de détail pour tracer la variation.")
        else:
            # mise en forme du graphbar
            fig_bar.update_layout(
                height=400,       # barres plus épaisses
                bargap=0.1,       # donner un peu de place entre les barres
                margin=dict(
                    l=140,
                    r=40,
                    t=60,
                    b=40
                )  # pour laisser de la place aux labels
            )
            fig_bar.update_traces(
                width=0.8   # 0.8 = 80% de la largeur dispo par catégorie
            )

            st.plotly_chart(
                fig_bar,
                use_container_width=True,
                key="pf_bar_portefeuille"
            )

    # ======================================================
    # TABLEAU
    # ======================================================

    # Colonnes de dimensions (classe / sous-classe) selon le niveau d'analyse
    if niveau_analyse == "Sous-classe d'actifs":
        # On affiche à la fois Classe d'actifs et Sous-classe d'actifs
        dim_cols = [
            (CLASS_COL, "Classe d'actifs"),
            (SUBCLASS_COL, "Sous-classe d'actifs"),
        ]
    else:
        # Vue agrégée uniquement par classe
        dim_cols = [
            (CLASS_COL, "Classe d'actifs"),
        ]

    # Colonnes de métriques
    metric_cols = [
        ("VM_FIN", "Valeur de Marché (M€)"),
        ("Delta_VM", "Δ VM (M€)"),
        ("Delta_VM_pct", "Δ VM (%)"),
        ("Tendance", "Tendance"),
        ("Alloc (%)", "Alloc (%)"),
        ("Δ Alloc (%)", "Δ Alloc (%)"),
    ]
    if has_VNC:
        metric_cols += [
            ("Delta_VNC_pct", "Effet Investissement (%)"),
            ("effet_marche", "Effet Marché (%)"),
        ]

    cols = dim_cols + metric_cols

    view = sort_portefeuille_pdf(view)
 
    # On ne garde que les colonnes qui existent dans view, puis on renomme
    aff = view[[c for c, _ in cols if c in view.columns]].rename(columns=dict(cols))

    # Compression des labels de classe dans le tableau principal (effet "groupé")
    if "Classe d'actifs" in aff.columns and "Sous-classe d'actifs" in aff.columns:
        aff = compress_group_labels(aff, "Classe d'actifs")
        mask_sub = aff["Sous-classe d'actifs"].astype(str).str.strip().ne("")
        aff.loc[mask_sub, "Sous-classe d'actifs"] = (
            aff.loc[mask_sub, "Sous-classe d'actifs"]
            .astype(str)
            .map(lambda x: f"   {x}" if x.strip() != "" else x)
        )

    # Formats d'affichage
    fmt_map = {}
    if "Valeur de Marché (M€)" in aff.columns:
        fmt_map["Valeur de Marché (M€)"] = fmt_meur
    if "Alloc (%)" in aff.columns:
        fmt_map["Alloc (%)"] = fmt_pct
    if "Δ Alloc (%)" in aff.columns:
        fmt_map["Δ Alloc (%)"] = fmt_pct
    if "Δ VM (M€)" in aff.columns:
        fmt_map["Δ VM (M€)"] = fmt_delta_meur
    if "Δ VM (%)" in aff.columns:
        fmt_map["Δ VM (%)"] = fmt_pct
    if "Effet Investissement (%)" in aff.columns:
        fmt_map["Effet Investissement (%)"] = fmt_pct
    if "Effet Marché (%)" in aff.columns:
        fmt_map["Effet Marché (%)"] = fmt_pct


    styler = apply_common_table_styles(aff, fmt_map=fmt_map)

    # Stockage pour l'onglet Rapport
    st.session_state["rapport_portefeuille"] = {
        "fig_pie": fig_pie,
        "fig_bar": fig_bar,
        "table": aff,
    }

    st.markdown(
        """
        <style>
        div[data-testid="stDataFrame"] div[role="columnheader"] {
            background-color: #714A80 !important;
            color: white !important;
            font-weight: bold !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    n_rows = len(aff)
    st.dataframe(
        styler,
        use_container_width=True,
        hide_index=True,
        height=35 * (n_rows + 1) + 3,
    )

    # ======================================================
    # EXPORT EXCEL
    # ======================================================
    excel_bytes = df_to_excel_bytes(aff, sheet_name="Données_PF")
    st.download_button(
        label="📥Télécharger en Excel",
        data=excel_bytes,
        file_name="Tableau_portefeuille.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ======================================================
    # TABLEAU DÉTAIL PAR TITRE
    # ======================================================
    st.markdown("---")
    show_detail = st.toggle("Afficher le détail par titre", value=False)
    if show_detail:

        detail_grp = [CLASS_COL, SUBCLASS_COL, "ID", "LIBELLE"]
        # On ne garde que les colonnes qui existent
        detail_grp = [c for c in detail_grp if c in df_filtre.columns]

        if len(detail_grp) >= 2:
            dff_det = df_filtre.copy()
            dff_det["DATE_TRANSPA"] = pd.to_datetime(dff_det["DATE_TRANSPA"]).dt.date

            debut_det = (
                dff_det[dff_det["DATE_TRANSPA"] == d0]
                .groupby(detail_grp, dropna=False)["VM_INIT"]
                .sum()
                .rename("VM_DEBUT")
            )
            fin_det = (
                dff_det[dff_det["DATE_TRANSPA"] == d1]
                .groupby(detail_grp, dropna=False)["VM_INIT"]
                .sum()
                .rename("VM_FIN")
            )
            res_det = pd.concat([debut_det, fin_det], axis=1).fillna(0).reset_index()
            res_det["Delta_VM"] = res_det["VM_FIN"] - res_det["VM_DEBUT"]
            res_det["Delta_VM_pct"] = np.where(
                res_det["VM_DEBUT"] != 0,
                res_det["Delta_VM"] / res_det["VM_DEBUT"],
                np.nan,
            )
            res_det["Tendance"] = res_det["Delta_VM_pct"].apply(trend)

            # Ligne TOTAL
            total_det = {
                CLASS_COL: "TOTAL", SUBCLASS_COL: "",
                "VM_DEBUT": res_det["VM_DEBUT"].sum(),
                "VM_FIN": res_det["VM_FIN"].sum(),
                "Delta_VM": res_det["Delta_VM"].sum(),
            }
            for c in detail_grp:
                if c not in total_det:
                    total_det[c] = ""
            t_deb = total_det["VM_DEBUT"]
            t_fin = total_det["VM_FIN"]
            t_delta = total_det["Delta_VM"]
            total_det["Delta_VM_pct"] = (t_delta / t_deb) if t_deb != 0 else np.nan
            total_det["Tendance"] = trend(total_det["Delta_VM_pct"])
            res_det = pd.concat([res_det, pd.DataFrame([total_det])], ignore_index=True)

            # Passage en M€ / %
            for c in ["VM_FIN", "Delta_VM"]:
                res_det[c] = res_det[c] / 1e6
            res_det["Delta_VM_pct"] = res_det["Delta_VM_pct"] * 100

            res_det = add_alloc_columns(res_det, vm_fin_col="VM_FIN", delta_vm_col="Delta_VM")

            # Renommage pour affichage
            rename_det = {
                CLASS_COL: "Classe d'actifs",
                SUBCLASS_COL: "Sous-classe d'actifs",
                "ID": "ID",
                "LIBELLE": "Libellé",
                "VM_FIN": "Valeur de Marché (M€)",
                "Delta_VM": "Δ VM (M€)",
                "Delta_VM_pct": "Δ VM (%)",
                "Tendance": "Tendance",
            }
            det_cols = [c for c in detail_grp + ["VM_FIN", "Delta_VM", "Delta_VM_pct", "Tendance", "Alloc (%)", "Δ Alloc (%)"] if c in res_det.columns]
            aff_det = res_det[det_cols].rename(columns=rename_det)

            # Même ordre que le tableau principal (hors TOTAL)
            mask_total = aff_det.apply(lambda r: "TOTAL" in r.astype(str).values, axis=1)
            aff_det_data = sort_portefeuille_pdf(aff_det[~mask_total])
            aff_det_total = aff_det[mask_total]
            aff_det = pd.concat([aff_det_data, aff_det_total], ignore_index=True)


            # --- Filtres ---
            mask_total_det = aff_det.apply(lambda r: "TOTAL" in r.astype(str).values, axis=1)
            aff_corps_det  = aff_det[~mask_total_det]
            aff_total_det  = aff_det[mask_total_det]

            fcol1, fcol2 = st.columns(2)

            with fcol1:
                if "Libellé" in aff_corps_det.columns:
                    search_lib = st.text_input("Libellé (recherche)", value="", key="det_pf_lib")
                else:
                    search_lib = ""
            with fcol2:
                if "ID" in aff_corps_det.columns:
                    search_id = st.text_input("ID (recherche)", value="", key="det_pf_id")
                else:
                    search_id = ""

            # Application des filtres
            filtered_det = aff_corps_det.copy()
            if search_lib and "Libellé" in filtered_det.columns:
                filtered_det = filtered_det[filtered_det["Libellé"].astype(str).str.contains(search_lib, case=False, na=False)]
            if search_id and "ID" in filtered_det.columns:
                filtered_det = filtered_det[filtered_det["ID"].astype(str).str.contains(search_id, case=False, na=False)]

            aff_det_filtered = pd.concat([filtered_det, aff_total_det], ignore_index=True)

            styler_det = apply_common_table_styles(aff_det_filtered)
            st.markdown("**Détail par titre**")
            n_det = len(aff_det_filtered)
            st.dataframe(
                styler_det,
                use_container_width=True,
                hide_index=True,
                height=35 * (n_det + 1) + 3,
            )
            excel_det = df_to_excel_bytes(aff_det, sheet_name="Détail_titres")
            st.download_button(
                label="📥Télécharger le détail en Excel",
                data=excel_det,
                file_name="detail_titres.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    
    
    
    
    
    
    
    
    
    
    
    
    
    