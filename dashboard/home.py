# dashboard/home.py

import streamlit as st
import pandas as pd
from pathlib import Path

from data import *              # doit exposer df_parent, df_transpa

from modules.tableau_data import tableau_data
from modules.portefeuille import render_portefeuille_tab
from modules.risque_spread import render_risque_spread_tab
from modules.risque_taux import render_risque_taux_tab
from modules.risque_action import render_risque_action_tab
from modules.risque_immo import render_risque_immo_tab
from modules.risque_autre import render_risque_autre_tab
from modules.rapport import build_portefeuille_block_for_report


# =========================
# WARMUP KALEIDO (arrière-plan)
# Lance Chromium en tâche de fond dès le démarrage du serveur.
# Quand l'utilisateur clique "Générer le PDF", Chromium est déjà chaud.
# @st.cache_resource = exécuté une seule fois par démarrage de serveur.
# =========================
@st.cache_resource(show_spinner=False)
def _start_kaleido_warmup():
    import threading
    def _warmup():
        try:
            import plotly.graph_objects as go
            import plotly.io as pio
            pio.to_image(go.Figure(), format="png", width=10, height=10, engine="kaleido")
        except Exception:
            pass
    t = threading.Thread(target=_warmup, daemon=True)
    t.start()

_start_kaleido_warmup()


# =========================
# CONFIG PAGE
# =========================
st.set_page_config(
    page_title="Dashboard Risques",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.subheader("🔔 Risques Financiers et Assurantiels")
st.markdown("##")

# Supprime le padding supérieur des composants Plotly dans les colonnes
# + Style sidebar Option A (violet foncé)
st.markdown(
    """
    <style>
    div[data-testid="stPlotlyChart"] > div { margin-top: 0 !important; padding-top: 0 !important; }
    div[data-testid="stPlotlyChart"] { margin-top: 0 !important; padding-top: 0 !important; overflow: visible !important; }
    /* Remonte la modebar au-dessus du graphique sans décaler le contenu */
    div[data-testid="stPlotlyChart"] .modebar-container {
        top: -26px !important;
        position: absolute !important;
    }

    /* ---- Masquer toolbar image (icône caméra + fullscreen) ---- */
    [data-testid="stImageActionButtons"] { display: none !important; }
    [data-testid="StyledFullScreenButton"] { display: none !important; }
    button[title="View fullscreen"] { display: none !important; }

    /* ---- Fond principal ---- */
    .stApp, .main .block-container {
        background-color: #f5f0fa !important;
    }

    /* ---- Onglets actifs : violet au lieu de rouge ---- */
    .stTabs [data-baseweb="tab-highlight"] {
        background-color: #714A80 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #714A80 !important;
        font-weight: 600;
    }

    /* ---- Multiselect et selectbox (hors sidebar) — fond blanc, bordure violette ---- */
    .stMultiSelect > div > div,
    .stSelectbox > div > div {
        background-color: white !important;
        border: 1.5px solid #c4a8d4 !important;
        border-radius: 6px !important;
    }
    /* Tags multiselect (hors sidebar) */
    .stMultiSelect span[data-baseweb="tag"] {
        background-color: #714A80 !important;
        color: white !important;
    }
    /* Supprimer la bordure interne dupliquée */
    .stMultiSelect > div > div > div,
    .stMultiSelect [data-baseweb="select"] > div {
        border: none !important;
        background-color: transparent !important;
    }

    /* ---- Radio buttons — supprime le fond sombre ---- */
    .stRadio [data-baseweb="radio"] {
        background-color: transparent !important;
    }
    .stRadio [data-baseweb="radio"] svg circle {
        fill: #714A80 !important;
        stroke: #714A80 !important;
    }

    /* ---- SIDEBAR Option A : fond violet foncé (plus sombre que primaryColor #714A80) ---- */
    section[data-testid="stSidebar"] {
        background-color: #4e3059 !important;
    }
    section[data-testid="stSidebar"] * {
        color: white !important;
    }
    /* Labels des widgets */
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stRadio label,
    section[data-testid="stSidebar"] .stMultiSelect label,
    section[data-testid="stSidebar"] .stToggle label {
        color: rgba(255,255,255,0.9) !important;
        font-weight: 600 !important;
    }
    /* Header "Filtres" */
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: white !important;
        border-bottom: 1px solid rgba(255,255,255,0.3);
        padding-bottom: 4px;
    }
    /* Inputs (selectbox, multiselect) — conteneur */
    section[data-testid="stSidebar"] .stSelectbox > div > div,
    section[data-testid="stSidebar"] .stMultiSelect > div > div {
        background-color: rgba(255,255,255,0.15) !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
        border-radius: 8px !important;
    }
    /* Supprimer les coins carrés des éléments internes du multiselect */
    section[data-testid="stSidebar"] .stMultiSelect > div > div > div,
    section[data-testid="stSidebar"] .stMultiSelect [data-baseweb="select"] > div {
        border: none !important;
        border-radius: 8px !important;
        background-color: transparent !important;
    }
    /* Texte dans selectbox et multiselect */
    section[data-testid="stSidebar"] .stSelectbox > div > div > div,
    section[data-testid="stSidebar"] .stMultiSelect > div > div > div,
    section[data-testid="stSidebar"] .stMultiSelect input,
    section[data-testid="stSidebar"] .stMultiSelect input::placeholder {
        color: white !important;
        background-color: transparent !important;
    }
    /* Zone de saisie multiselect */
    section[data-testid="stSidebar"] .stMultiSelect [data-baseweb="input"] {
        background-color: transparent !important;
    }
    /* Tags multiselect */
    section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] {
        background-color: rgba(255,255,255,0.25) !important;
        color: white !important;
    }
    /* Icône X dans les tags */
    section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] span {
        color: white !important;
    }
    /* Radio buttons — labels */
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
        color: rgba(255,255,255,0.9) !important;
    }
    /* Option sélectionnée : fond blanc semi-transparent + texte en gras */
    section[data-testid="stSidebar"] .stRadio [data-baseweb="radio"]:has(input:checked) {
        background-color: rgba(255,255,255,0.22) !important;
        border-radius: 8px !important;
        padding: 4px 8px !important;
    }
    section[data-testid="stSidebar"] .stRadio [data-baseweb="radio"]:has(input:checked) label {
        font-weight: 700 !important;
        color: white !important;
    }
    /* Options non sélectionnées : légèrement atténuées */
    section[data-testid="stSidebar"] .stRadio [data-baseweb="radio"]:not(:has(input:checked)) label {
        color: rgba(255,255,255,0.65) !important;
    }

    /* Toggle — label texte */
    section[data-testid="stSidebar"] [data-testid="stToggle"] p,
    section[data-testid="stSidebar"] .stToggle p {
        color: rgba(255,255,255,0.9) !important;
    }
    /* Caption logo */
    section[data-testid="stSidebar"] .stImage figcaption {
        color: rgba(255,255,255,0.7) !important;
    }
    /* Markdown texte */
    section[data-testid="stSidebar"] .stMarkdown p {
        color: rgba(255,255,255,0.85) !important;
    }
    /* Séparateur */
    section[data-testid="stSidebar"] hr {
        border-color: rgba(255,255,255,0.25) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# SIDEBAR : LOGO
# =========================
_LOGO_PATH = Path(__file__).resolve().parent.parent / "data" / "logo" / "logoeps.png"
if _LOGO_PATH.exists():
    st.sidebar.image(str(_LOGO_PATH), caption="Tableau de bord")


# =========================
# LOGIQUE FILTRES & df_selection (TA LOGIQUE)
# =========================

def _reset_filters():
    # à l'activation / changement de source, on réinitialise les filtres
    for k in list(st.session_state.keys()):
        if k.startswith("filter_"):
            del st.session_state[k]


# Toggle base Transpa / Parent
use_transpa = st.sidebar.toggle(
    "Base Transpa",
    value=False,
    key="use_transpa",
    on_change=_reset_filters,
)




# ---- Dataframe actif selon le toggle pour TOUTE l'application ----
df = df_transpa if use_transpa else df_parent
df = df.copy()  # Copie pour éviter les modifications non voulues

# ----- Normalisation des noms de colonnes -----
df.columns = (
    df.columns
    .astype(str)
    .str.replace('\ufeff', '', regex=True)  # Enlever BOM si présent
    .str.strip()                            # Trim
    .str.upper()                            # Majuscules
)

# ---- Vérification de la présence des colonnes de date nécessaires ----
Date_candidate = ["DATE_TRANSPA"]
date_col = next((col for col in Date_candidate if col in df.columns), None)
if not date_col:
    st.error(f"Aucune colonne trouvée parmi {Date_candidate}. Colonnes: {df.columns.tolist()}")
    st.stop()

# ---- Affichage de la source active ----
st.sidebar.markdown(f"Source active : **{'Base Transpa' if use_transpa else 'Base Parent'}**")

# ---- Switcher Filtres ----
st.sidebar.header("Filtres")

# ---- Filtre des dates ----
df[date_col] = pd.to_datetime(df[date_col], errors='coerce', dayfirst=True)

# On récupère les dates uniques normalisées
dates_uniques = df[date_col].dropna().dt.normalize().unique()
dates_uniques = pd.to_datetime(sorted(dates_uniques))

n = len(dates_uniques)
idx_end = n - 1                # date la plus récente
idx_start = max(n - 2, 0)      # date t-1 si possible

date_debut = st.sidebar.selectbox(
    "📅 Date de Début",
    options=dates_uniques,
    index=idx_start,
    format_func=lambda x: x.strftime("%d-%m-%Y"),
    key="date_debut",
)

date_fin = st.sidebar.selectbox(
    "📅 Date de Fin",
    options=dates_uniques,
    index=idx_end,
    format_func=lambda x: x.strftime("%d-%m-%Y"),
    key="date_fin",
)

# Sécurité: début <= fin
if date_debut > date_fin:
    date_debut, date_fin = date_fin, date_debut
    st.sidebar.info("Les dates ont été inversées pour former un intervalle valide.")

# ---- Sélection du Portefeuille ----
if "GROUPE" not in df.columns:
    st.error("Colonne 'GROUPE' manquante dans la base.")
    st.stop()

groupes = sorted(df["GROUPE"].dropna().unique().tolist())
if "EPS" not in groupes:
    groupes.insert(0, "EPS")  # On force l'option EPS

portefeuil = st.sidebar.radio(
    "Choisir le Portefeuille",
    options=groupes,
    index=groupes.index("EPS") if "EPS" in groupes else 0,
    key="pf",
)

# ---- Sélection des cantons ----
if "CANTON" not in df.columns:
    st.error("Colonne 'CANTON' manquante dans la base.")
    st.stop()

if portefeuil == "EPS":
    cantons_options = sorted(df["CANTON"].dropna().unique().tolist())
else:
    cantons_options = sorted(
        df[df["GROUPE"] == portefeuil]["CANTON"].dropna().unique().tolist()
    )

# Initialiser la sélection si absente
if "canton" not in st.session_state:
    st.session_state["canton"] = cantons_options

# Quand on passe à EPS, sélectionner tous les cantons automatiquement
if portefeuil == "EPS" and st.session_state.get("_prev_pf") != "EPS":
    st.session_state["canton"] = cantons_options

st.session_state["_prev_pf"] = portefeuil

# S'assurer que la sélection actuelle est valide pour les options disponibles
valid = [c for c in st.session_state["canton"] if c in cantons_options]
st.session_state["canton"] = valid or cantons_options

canton = st.sidebar.multiselect(
    "Choisir le Canton",
    options=cantons_options,
    key="canton",
)

# ---- Sélection des données selon le portefeuille ----
if portefeuil == "EPS":
    selection_pf = pd.Series(True, index=df.index)  # EPS = pas de filtre
else:
    selection_pf = (df["GROUPE"] == portefeuil)     # Filtre sur le groupe choisi

# ---- Sélection des données selon le canton ----
mask_canton = df["CANTON"].isin(canton)

# ---- Filtre des dates ----
mask_date = df[date_col].dt.normalize().isin([date_debut.normalize(), date_fin.normalize()])

# ---- Filtre combiné ----
filtre_pf_canton = selection_pf & mask_canton

# ---- Application des filtres ----
df_selection = df[filtre_pf_canton & mask_date].copy()

# Disponibiliser la sélection pour les autres pages
st.session_state["df_selection"] = df_selection


# =========================
# ONGLES PRINCIPAUX
# =========================
suivi_pf_tab, suivi_indic_tab, data_tab, rapport_tab = st.tabs(
    ["Suivi du Portefeuille", "Suivi des Indicateurs de Risque", "Data", "Rapport"]
)

# =========================
# ONGLET : SUIVI DU PORTEFEUILLE
# =========================
with suivi_pf_tab:
    (
        portefeuil_tab,
        risque_taux_tab,
        risque_spread_tab,
        risque_action_tab,
        risque_immo_tab,
        #risque_autre_tab,
    ) = st.tabs(
        [
            "Portefeuille",
            "Risque Taux",
            "Risque Spread",
            "Risque Action",
            "Risque Immobilier",
            #"Risque Autre",
        ]
    )

    # Portefeuille
    with portefeuil_tab:
        # ── KPI cards ────────────────────────────────────────────────────────
        _df = df_selection.copy()
        _date_col = next((c for c in ["DATE_TRANSPA", "DATE_VALEUR"] if c in _df.columns), None)
        _class_col = next((c for c in ["CLASSIF_RF", "CLASSE_ACTIF"] if c in _df.columns), None)

        _kpi_ok = False
        if _date_col and "VM_INIT" in _df.columns:
            _df[_date_col] = pd.to_datetime(_df[_date_col]).dt.date
            _d0 = _df.loc[_df[_date_col] <= pd.to_datetime(date_debut).date(), _date_col].max()
            _d1 = _df.loc[_df[_date_col] <= pd.to_datetime(date_fin).date(), _date_col].max()

            if pd.notna(_d0) and pd.notna(_d1):
                _vm0 = _df[_df[_date_col] == _d0]["VM_INIT"].sum() / 1e6
                _vm1 = _df[_df[_date_col] == _d1]["VM_INIT"].sum() / 1e6
                _delta_meur = _vm1 - _vm0
                _delta_pct  = (_delta_meur / _vm0 * 100) if _vm0 != 0 else float("nan")

                def _fmt_fr(v, suffix=""):
                    s = f"{v:,.1f}".replace(",", " ").replace(".", ",")
                    return f"{s}{suffix}"

                def _tendance(pct):
                    if pd.isna(pct): return "◆ Stable", "#f1c40f"
                    if pct >  0.5:   return "▲ Hausse", "#2ca02c"
                    if pct < -0.5:   return "▼ Baisse", "#d62728"
                    return "◆ Stable", "#f1c40f"

                _tend_txt, _tend_col = _tendance(_delta_pct)
                _signe = "+" if _delta_meur >= 0 else ""

                _classe_hausse = _classe_baisse = "—"
                _pct_hausse = _pct_baisse = float("nan")
                if _class_col:
                    _g0 = _df[_df[_date_col] == _d0].groupby(_class_col)["VM_INIT"].sum()
                    _g1 = _df[_df[_date_col] == _d1].groupby(_class_col)["VM_INIT"].sum()
                    _gall = pd.concat([_g0.rename("d0"), _g1.rename("d1")], axis=1).fillna(0)
                    _gall["pct"] = (_gall["d1"] - _gall["d0"]) / _gall["d0"].replace(0, float("nan")) * 100
                    _gall = _gall.dropna(subset=["pct"])
                    if not _gall.empty:
                        _idx_h = _gall["pct"].idxmax()
                        _idx_b = _gall["pct"].idxmin()
                        _classe_hausse = str(_idx_h)
                        _classe_baisse = str(_idx_b)
                        _pct_hausse    = _gall.loc[_idx_h, "pct"]
                        _pct_baisse    = _gall.loc[_idx_b, "pct"]

                _kpi_ok = True

        def _card(titre, valeur, sous_valeur, couleur_sous="#555", icone=""):
            return f"""
            <div style="background:white;border-radius:12px;padding:22px 20px 18px;
                        box-shadow:0 2px 10px rgba(113,74,128,0.12);
                        border-top:4px solid #714A80;text-align:center;height:160px;
                        display:flex;flex-direction:column;justify-content:space-between;">
                <div style="font-size:13px;font-weight:600;color:#714A80;letter-spacing:.5px;text-transform:uppercase;">
                    {titre}
                </div>
                <div style="font-size:26px;font-weight:700;color:#1a1a2e;">
                    {icone}{valeur}
                </div>
                <div style="font-size:14px;font-weight:600;color:{couleur_sous};">
                    {sous_valeur}
                </div>
            </div>"""

        if _kpi_ok:
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                st.markdown(_card(
                    "Valeur de Marché",
                    _fmt_fr(_vm1, " M€"),
                    f"au {pd.Timestamp(_d1).strftime('%d-%m-%Y')}",
                ), unsafe_allow_html=True)
            with c2:
                st.markdown(_card(
                    "Variation VM (M€)",
                    f"{_signe}{_fmt_fr(_delta_meur, ' M€')}",
                    _tend_txt,
                    couleur_sous=_tend_col,
                ), unsafe_allow_html=True)
            with c3:
                st.markdown(_card(
                    "Variation VM (%)",
                    f"{_signe}{_fmt_fr(_delta_pct, ' %')}",
                    _tend_txt,
                    couleur_sous=_tend_col,
                ), unsafe_allow_html=True)
            with c4:
                _s3 = "+" if _pct_hausse >= 0 else ""
                st.markdown(_card(
                    "Classe en Hausse",
                    _classe_hausse,
                    f"{_s3}{_fmt_fr(_pct_hausse, ' %')}" if not pd.isna(_pct_hausse) else "—",
                    couleur_sous="#2ca02c",
                    icone="▲ ",
                ), unsafe_allow_html=True)
            with c5:
                st.markdown(_card(
                    "Classe en Baisse",
                    _classe_baisse,
                    f"{_fmt_fr(_pct_baisse, ' %')}" if not pd.isna(_pct_baisse) else "—",
                    couleur_sous="#d62728",
                    icone="▼ ",
                ), unsafe_allow_html=True)
        else:
            st.info("Données insuffisantes pour calculer les indicateurs.")

        st.markdown("---")

        render_portefeuille_tab(
            df_selection=df_selection,
            use_transpa=use_transpa,
            date_debut=date_debut,
            date_fin=date_fin,
        )

    # Risque Taux
    with risque_taux_tab:
        render_risque_taux_tab(
            df_selection=df_selection,
            date_debut=date_debut,
            date_fin=date_fin,
        )

    # Risque Spread
    with risque_spread_tab:
        render_risque_spread_tab(
            df_selection=df_selection,
            date_debut=date_debut,
            date_fin=date_fin,
        )

    # Risque Action
    with risque_action_tab:
        render_risque_action_tab(
            df_selection=df_selection,
            date_debut=date_debut,
            date_fin=date_fin,
        )

    # Risque Immobilier
    with risque_immo_tab:
        render_risque_immo_tab(
            df_selection=df_selection,
            date_debut=date_debut,
            date_fin=date_fin,
        )

    # Risque Autre
    #with risque_autre_tab:
     #   render_risque_autre_tab(
      #      df_selection=df_selection,
       #     date_debut=date_debut,
        #    date_fin=date_fin,
        #)

# =========================
# ONGLET : INDICATEURS DE RISQUE (à compléter)
# =========================
with suivi_indic_tab:
    st.markdown("### Suivi des indicateurs de risque globaux")
    st.info("Contenu à venir.")

# =========================
# ONGLET : DATA
# =========================
with data_tab:
    tableau_data(df_selection)
    
# =========================
# ONGLET : RAPPORT
# =========================
with rapport_tab:
    build_portefeuille_block_for_report(
        df_selection=df_selection,
        use_transpa=use_transpa,
        date_debut=date_debut,
        date_fin=date_fin,
    )