# dashboard/home.py

import sys as _sys
import streamlit as st
import pandas as pd
from pathlib import Path

# Rendre data/ importable (contient app_config, refresh_data…)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
if str(_DATA_DIR) not in _sys.path:
    _sys.path.insert(0, str(_DATA_DIR))

from app_config import (  # type: ignore
    load_config, save_config, ROLES,
    get_users, add_user, delete_user, set_user_active, update_password,
)

import streamlit_authenticator as stauth

from modules.tableau_data import tableau_data
from modules.portefeuille import render_portefeuille_tab
from modules.risque_spread import render_risque_spread_tab
from modules.risque_taux import render_risque_taux_tab
from modules.risque_action import render_risque_action_tab
from modules.risque_immo import render_risque_immo_tab

from modules.rapport import build_portefeuille_block_for_report
from pandas.tseries.offsets import MonthEnd


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

# Chargement de la config persistante (une fois par rerun)
if "app_config" not in st.session_state:
    st.session_state["app_config"] = load_config()
_cfg = st.session_state["app_config"]

# Supprime le padding supérieur des composants Plotly dans les colonnes
# + Style sidebar Option A (violet foncé)
st.markdown(
    """
    <style>
    div[data-testid="stPlotlyChart"] > div { margin-top: 0 !important; padding-top: 0 !important; }
    div[data-testid="stPlotlyChart"] { margin-top: 0 !important; padding-top: 0 !important; overflow: visible !important; }
    /* Décale la modebar vers le haut pour ne pas chevaucher la figure */
    div[data-testid="stPlotlyChart"] .modebar { margin-top: -10px !important; }

    /* ---- Masquer toolbar image (icône caméra) ---- */
    [data-testid="stImageActionButtons"] { display: none !important; }

    /* ---- Fond principal ---- */
    .stApp, .main .block-container {
        background-color: #f5f0fa !important;
    }
    /* ---- Réduction du padding supérieur ---- */
    .main .block-container {
        padding-top: 1rem !important;
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
    /* Text input sidebar — une seule couche */
    section[data-testid="stSidebar"] .stTextInput > div > div {
        background-color: rgba(255,255,255,0.15) !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
        border-radius: 8px !important;
    }
    section[data-testid="stSidebar"] .stTextInput > div {
        background-color: transparent !important;
        border: none !important;
    }
    section[data-testid="stSidebar"] .stTextInput input {
        background-color: transparent !important;
        color: white !important;
        -webkit-text-fill-color: white !important;
        border: none !important;
        box-shadow: none !important;
    }
    section[data-testid="stSidebar"] .stTextInput input::placeholder {
        color: rgba(255,255,255,0.55) !important;
        -webkit-text-fill-color: rgba(255,255,255,0.55) !important;
    }
    /* Masquer "Press Enter to apply / submit" partout dans l'app */
    [data-testid="InputInstructions"],
    .stTextInput small {
        display: none !important;
    }
    section[data-testid="stSidebar"] .stTextInput > div > div:focus-within {
        border-color: rgba(255,255,255,0.6) !important;
        box-shadow: none !important;
    }
    /* Icône œil (afficher/masquer mot de passe) */
    section[data-testid="stSidebar"] .stTextInput button,
    section[data-testid="stSidebar"] .stTextInput button svg {
        color: rgba(255,255,255,0.7) !important;
        fill: rgba(255,255,255,0.7) !important;
        background-color: transparent !important;
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

    /* Espacement entre les titres de section et leurs widgets */
    section[data-testid="stSidebar"] .stRadio,
    section[data-testid="stSidebar"] .stMultiSelect,
    section[data-testid="stSidebar"] .stTextInput {
        margin-top: 10px !important;
    }

    /* Bouton Se déconnecter */
    section[data-testid="stSidebar"] .stButton > button {
        width: 100% !important;
        background-color: transparent !important;
        border: 1px solid rgba(255,255,255,0.35) !important;
        border-radius: 8px !important;
        color: rgba(255,255,255,0.8) !important;
        font-weight: 500 !important;
        padding: 8px 12px !important;
        transition: background-color 0.2s, border-color 0.2s;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background-color: rgba(220,53,69,0.25) !important;
        border-color: rgba(220,53,69,0.7) !important;
        color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# AUTHENTIFICATION
# =========================
_LOGO_PATH = Path(__file__).resolve().parent.parent / "data" / "logo" / "logoeps.png"

# Construit le dict de credentials pour stauth à partir des utilisateurs actifs
_auth_credentials = {
    "usernames": {
        u["username"]: {
            "name":     u["username"],
            "password": u["password_hash"],
        }
        for u in get_users(_cfg)
        if u.get("active", True)
    }
}

_authenticator = stauth.Authenticate(
    _auth_credentials,
    cookie_name="risk_dashboard_auth",
    cookie_key=_cfg.get("cookie_key", "risk_dashboard_secret_key"),
    cookie_expiry_days=1,
    auto_hash=False,   # hashes déjà en bcrypt
)

_already_auth = st.session_state.get("authentication_status") is True

if not _already_auth:
    # CSS uniquement pour la page de login (fond sombre + formulaire thème violet)
    st.markdown(
        """
        <style>
        .stApp, .main .block-container { background-color: #4e3059 !important; }
        [data-testid="stForm"] {
            background-color: rgba(255,255,255,0.08) !important;
            border: 1px solid rgba(255,255,255,0.2) !important;
            border-radius: 14px !important;
            padding: 28px 24px !important;
            margin-top: 8px !important;
        }
        [data-testid="stForm"] h2, [data-testid="stForm"] h3 {
            color: white !important; text-align: center !important; border: none !important;
        }
        [data-testid="stForm"] label {
            color: rgba(255,255,255,0.9) !important; font-weight: 600 !important;
        }
        /* Conteneur champ (deux sélecteurs pour compatibilité) */
        [data-testid="stForm"] [data-baseweb="input"],
        [data-testid="stForm"] .stTextInput > div > div {
            background-color: rgba(255,255,255,0.15) !important;
            border: 1px solid rgba(255,255,255,0.35) !important;
            border-radius: 8px !important;
            box-shadow: none !important;
        }
        /* Wrapper intermédiaire — pas de bordure en double */
        [data-testid="stForm"] .stTextInput > div {
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        /* Texte saisi */
        [data-testid="stForm"] input,
        [data-testid="stForm"] .stTextInput input {
            color: white !important;
            -webkit-text-fill-color: white !important;
            background-color: transparent !important;
            caret-color: white !important;
        }
        /* Autofill navigateur — hack box-shadow pour écraser le fond blanc imposé */
        [data-testid="stForm"] input:-webkit-autofill,
        [data-testid="stForm"] input:-webkit-autofill:hover,
        [data-testid="stForm"] input:-webkit-autofill:focus,
        [data-testid="stForm"] input:-webkit-autofill:active {
            -webkit-box-shadow: 0 0 0 1000px rgba(78,48,89,0.95) inset !important;
            -webkit-text-fill-color: white !important;
            caret-color: white !important;
            transition: background-color 5000s ease-in-out 0s;
        }
        [data-testid="stForm"] input::placeholder {
            color: rgba(255,255,255,0.45) !important;
            -webkit-text-fill-color: rgba(255,255,255,0.45) !important;
        }
        /* Focus */
        [data-testid="stForm"] [data-baseweb="input"]:focus-within,
        [data-testid="stForm"] .stTextInput > div > div:focus-within {
            border-color: rgba(255,255,255,0.7) !important;
            box-shadow: 0 0 0 2px rgba(255,255,255,0.12) !important;
        }
        /* Icône œil */
        [data-testid="stForm"] .stTextInput button,
        [data-testid="stForm"] .stTextInput button svg {
            color: rgba(255,255,255,0.7) !important;
            fill: rgba(255,255,255,0.7) !important;
            background-color: transparent !important;
        }
        [data-testid="stForm"] .stFormSubmitButton > button {
            background-color: #714A80 !important; color: white !important;
            border: none !important; border-radius: 8px !important;
            width: 100% !important; font-weight: 600 !important; margin-top: 6px !important;
        }
        [data-testid="stForm"] .stFormSubmitButton > button:hover {
            background-color: #8a5d9a !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _lcol1, _lcol2, _lcol3 = st.columns([1, 1.2, 1])
    with _lcol2:
        if _LOGO_PATH.exists():
            import base64 as _b64
            _logo_b64 = _b64.b64encode(open(str(_LOGO_PATH), "rb").read()).decode()
            st.markdown(
                f"""<div style="display:flex;justify-content:center;margin-bottom:12px;">
                        <img src="data:image/png;base64,{_logo_b64}"
                             style="width:260px;max-width:100%;border-radius:16px;">
                    </div>""",
                unsafe_allow_html=True,
            )
        _login_result = _authenticator.login(
            location="main",
            fields={
                "Form name": "Connexion — Dashboard Risques",
                "Username":  "Identifiant",
                "Password":  "Mot de passe",
                "Login":     "Se connecter",
            },
        )
else:
    _login_result = _authenticator.login(location="unrendered")

# 0.4.x : retourne un tuple OU None (premier rendu / re-auth cookie)
# Les valeurs sont toujours disponibles dans st.session_state
if _login_result is not None:
    _name, _auth_status, _username = _login_result
else:
    _name        = st.session_state.get("name")
    _auth_status = st.session_state.get("authentication_status")
    _username    = st.session_state.get("username")

if _auth_status is False:
    st.error("Identifiant ou mot de passe incorrect.")
    st.stop()
elif _auth_status is None:
    st.stop()

# ── Utilisateur connecté : restaurer le fond et les formulaires du dashboard ──
st.markdown(
    """
    <style>
    /* ── Fond principal ── */
    .stApp, .main .block-container {
        background-color: #f5f0fa !important;
    }

    /* ── Textes et labels (écrase les règles login texte blanc) ── */
    .main label,
    .main p,
    .main h1, .main h2, .main h3, .main h4,
    .main .stMarkdown p,
    .main [data-testid="stText"],
    .main [data-testid="stCaption"] {
        color: #1a1a2e !important;
        -webkit-text-fill-color: #1a1a2e !important;
    }

    /* ── Formulaires : carte blanche ── */
    .main [data-testid="stForm"] {
        background-color: white !important;
        border: 1px solid #d9c8e8 !important;
        border-radius: 10px !important;
        padding: 20px !important;
    }

    /* ── Text inputs — deux sélecteurs pour compatibilité Streamlit ── */
    .main .stTextInput > div > div,
    .main .stTextInput [data-baseweb="input"] {
        background-color: white !important;
        border: 1.5px solid #c4a8d4 !important;
        border-radius: 6px !important;
        box-shadow: none !important;
    }
    .main .stTextInput > div {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    .main .stTextInput input,
    .main .stTextInput [data-baseweb="input"] input {
        color: #1a1a2e !important;
        -webkit-text-fill-color: #1a1a2e !important;
        background-color: transparent !important;
    }
    .main .stTextInput input::placeholder {
        color: #999 !important;
        -webkit-text-fill-color: #999 !important;
    }
    .main .stTextInput button,
    .main .stTextInput button svg {
        color: #714A80 !important;
        fill: #714A80 !important;
        background-color: transparent !important;
    }
    /* Focus ring */
    .main .stTextInput > div > div:focus-within,
    .main .stTextInput [data-baseweb="input"]:focus-within {
        border-color: #714A80 !important;
        box-shadow: 0 0 0 2px rgba(113,74,128,0.15) !important;
    }

    /* ── Selectbox ── */
    .main .stSelectbox > div > div,
    .main .stSelectbox [data-baseweb="select"] > div {
        background-color: white !important;
        border: 1.5px solid #c4a8d4 !important;
        border-radius: 6px !important;
        box-shadow: none !important;
    }
    .main .stSelectbox > div > div > div,
    .main .stSelectbox [data-baseweb="select"] > div > div {
        color: #1a1a2e !important;
        -webkit-text-fill-color: #1a1a2e !important;
        background-color: transparent !important;
    }
    /* Icône flèche selectbox */
    .main .stSelectbox [data-baseweb="select"] svg {
        fill: #714A80 !important;
    }

    /* ── Number input ── */
    .main .stNumberInput > div > div,
    .main .stNumberInput [data-baseweb="input"] {
        background-color: white !important;
        border: 1.5px solid #c4a8d4 !important;
        border-radius: 6px !important;
    }
    .main .stNumberInput input {
        color: #1a1a2e !important;
        -webkit-text-fill-color: #1a1a2e !important;
        background-color: transparent !important;
    }

    /* ── Toggle (hors sidebar) ── */
    .main .stToggle label,
    .main [data-testid="stToggle"] p {
        color: #1a1a2e !important;
        -webkit-text-fill-color: #1a1a2e !important;
    }

    /* ── Multiselect (hors sidebar) ── */
    .main .stMultiSelect > div > div,
    .main .stMultiSelect [data-baseweb="select"] > div {
        background-color: white !important;
        border: 1.5px solid #c4a8d4 !important;
        border-radius: 6px !important;
    }
    .main .stMultiSelect [data-baseweb="input"] {
        background-color: transparent !important;
        border: none !important;
    }
    .main .stMultiSelect input,
    .main .stMultiSelect [data-baseweb="select"] > div > div {
        color: #1a1a2e !important;
        -webkit-text-fill-color: #1a1a2e !important;
    }

    /* ── Boutons submit de formulaire ── */
    .main .stFormSubmitButton > button {
        background-color: #714A80 !important;
        color: white !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    .main .stFormSubmitButton > button:hover {
        background-color: #8a5d9a !important;
    }

    /* ── Boutons standard (hors sidebar) ── */
    .main .stButton > button {
        background-color: white !important;
        color: #714A80 !important;
        border: 1.5px solid #c4a8d4 !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
    }
    .main .stButton > button:hover {
        background-color: #f0e6f8 !important;
        border-color: #714A80 !important;
    }

    /* ── Dataframes ── */
    .main [data-testid="stDataFrame"] {
        background-color: white !important;
        border-radius: 8px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

from data import load_df  # type: ignore[import]

df_parent  = load_df("base_parent")
df_transpa = load_df("base_transpa")

# Rôle de l'utilisateur connecté — comparaison insensible à la casse (stauth lowercase les usernames)
_user_data  = next((u for u in get_users(st.session_state["app_config"]) if u["username"].lower() == (_username or "").lower()), {})
_user_role  = _user_data.get("role", "Lecteur")

# Réinitialise le toggle admin si c'est un nouvel utilisateur qui se connecte
# (évite qu'un session_state résiduel de la session précédente cache l'onglet Admin)
if st.session_state.get("_logged_in_user") != _username:
    st.session_state["_logged_in_user"] = _username
    st.session_state.pop("show_admin_tab", None)

# =========================
# HEADER
# =========================
st.subheader("🔔 Risques Financiers et Assurantiels")

# =========================
# SIDEBAR : LOGO + DÉCONNEXION
# =========================
if _LOGO_PATH.exists():
    st.sidebar.image(str(_LOGO_PATH))

st.sidebar.markdown(
    f"<div style='margin-bottom:10px;'>👤 <strong>{_username}</strong> — <em>{_user_role}</em></div>",
    unsafe_allow_html=True,
)


# =========================
# LOGIQUE FILTRES & df_selection
# =========================

def _reset_filters():
    # Réinitialise les filtres dépendants de la source (canton, portefeuille, dates)
    # appelé quand on bascule Base Parent ↔ Base Transpa
    for k in ["canton", "pf", "date_debut", "date_fin"]:
        if k in st.session_state:
            del st.session_state[k]


# Toggle base Transpa / Parent
st.sidebar.header("Source des données")
col1, col2 = st.sidebar.columns([1, 3])

with col1:
    use_transpa = st.toggle(
        "",
        value=False,
        key="use_transpa",
        on_change=_reset_filters,
    )
    
with col2:
    source_label= "Base Transpa" if use_transpa else "Base Parent"
    st.markdown(
        f"<p style='color: white; font-weight: 600; padding-top:6px;'>{source_label}</p>",
        unsafe_allow_html=True,
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

# ---- Switcher Filtres ----

# ---- Filtre des dates ----
st.sidebar.subheader("Période d'analyse")
df[date_col] = pd.to_datetime(df[date_col], errors='coerce', dayfirst=True)

# On récupère les dates uniques normalisées
dates_uniques = df[date_col].dropna().dt.normalize().unique()
dates_uniques = pd.to_datetime(sorted(dates_uniques))

# filtrage: fin de mois ou date la plus proche
def filter_end_of_month(dates):
    result = []
    # Grouper par année et mois
    df_dates = pd.DataFrame({'date': dates})
    df_dates['month_key'] = df_dates['date'].dt.to_period('M')
    
    for period, group in df_dates.groupby('month_key'):
        # Calcule de la vraie fin de mois
        fin_mois = (period.to_timestamp() + MonthEnd(0)).normalize()
        
        if fin_mois in group['date'].values:
            # La fin de mois est présente, on la prend
            result.append(fin_mois)
        else:
            # Si la fin de mois n'est pas présente, prendre la date la plus proche
            result.append(group['date'].max())  # La date la plus récente du mois disponible
    
    return pd.to_datetime(sorted(result))
            

dates_uniques = filter_end_of_month(dates_uniques)

n = len(dates_uniques)
idx_end = n - 1                # date la plus récente (T)
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
st.sidebar.markdown("### Portefeuille")
if "GROUPE" not in df.columns:
    st.error("Colonne 'GROUPE' manquante dans la base.")
    st.stop()

groupes = sorted(df["GROUPE"].dropna().unique().tolist())
if "EPS" not in groupes:
    groupes.insert(0, "EPS")

portefeuil = st.sidebar.radio(
    "Portefeuille",
    options=groupes,
    index=groupes.index("EPS") if "EPS" in groupes else 0,
    key="pf",
    label_visibility="collapsed",
)

# ---- Sélection des cantons ----
st.sidebar.markdown("### Canton")
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
    "Canton",
    options=cantons_options,
    key="canton",
    label_visibility="collapsed",
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

# ---- Protection contre une sélection vide ----
if not canton:
    st.sidebar.warning("Aucun canton sélectionné — veuillez en choisir au moins un.")
    st.stop()

if df_selection.empty:
    st.sidebar.warning("Aucune donnée pour les filtres sélectionnés.")
    st.stop()

# Disponibiliser la sélection pour les autres pages
st.session_state["df_selection"] = df_selection

# =========================
# SIDEBAR : ADMIN
# =========================
show_admin = False
if _user_role == "Admin":
    st.sidebar.markdown("### Administration")
    show_admin = st.sidebar.toggle(
        "Afficher l'onglet Admin",
        value=True,
        key="show_admin_tab",
    )

_authenticator.logout("⏻  Se déconnecter", location="sidebar", key="btn_logout")


# =========================
# ONGLES PRINCIPAUX
# =========================
_tab_labels = ["Suivi du Portefeuille", "Suivi des Indicateurs de Risque", "Data", "Rapport"]
if show_admin:
    _tab_labels.append("⚙️ Admin")

_tabs = st.tabs(_tab_labels)
suivi_pf_tab      = _tabs[0]
suivi_indic_tab   = _tabs[1]
data_tab          = _tabs[2]
rapport_tab       = _tabs[3]
admin_tab         = _tabs[4] if show_admin else None

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

# =========================
# ONGLET : ADMIN
# =========================
if show_admin and admin_tab is not None:
    with admin_tab:
        st.subheader("⚙️ Administration")
        admin_data_tab, admin_params_tab, admin_diag_tab, admin_users_tab = st.tabs([
            "📂 Données",
            "⚙️ Paramètres",
            "🔍 Diagnostics",
            "👤 Utilisateurs / Accès",
        ])

        with admin_data_tab:
            import datetime as _dt
            from refresh_data import FICHIERS, refresh_all, source_available  # type: ignore

            st.markdown("### Données sources")

            # ── Statut des fichiers CSV nettoyés ──────────────────────────────
            _status_rows = []
            for _name, _cfg in FICHIERS.items():
                _csv = _cfg["cleaned"]
                if _csv.exists():
                    _stat  = _csv.stat()
                    _mtime = _dt.datetime.fromtimestamp(_stat.st_mtime).strftime("%d/%m/%Y %H:%M")
                    _size  = _stat.st_size
                    _size_str = (
                        f"{_size / 1024**2:.2f} Mo" if _size >= 1024**2
                        else f"{_size / 1024:.1f} Ko" if _size >= 1024
                        else f"{_size} o"
                    )
                    try:
                        _nrows = sum(1 for _ in open(_csv, encoding="utf-8-sig")) - 1
                    except Exception:
                        _nrows = "—"
                    _status_rows.append({
                        "Fichier": _csv.name,
                        "Dernière MAJ": _mtime,
                        "Taille": _size_str,
                        "Lignes": f"{_nrows:,}".replace(",", " ") if isinstance(_nrows, int) else _nrows,
                        "État": "✅ OK",
                    })
                else:
                    _status_rows.append({
                        "Fichier": _cfg["cleaned"].name,
                        "Dernière MAJ": "—",
                        "Taille": "—",
                        "Lignes": "—",
                        "État": "⚠️ Absent",
                    })

            st.dataframe(
                pd.DataFrame(_status_rows),
                use_container_width=True,
                hide_index=True,
            )

            # ── Statut du montage réseau ──────────────────────────────────────
            import subprocess as _sp

            _mount_path = Path("/mnt/risques")
            _source_ok  = source_available(_cfg.get("source_dir"))

            st.markdown("---")
            st.markdown("### Accès au répertoire source")

            if _source_ok:
                st.success(f"Répertoire source accessible : `{_mount_path}`")
            else:
                st.error(f"Répertoire source inaccessible : `{_mount_path}` n'est pas monté.")

                col_mount, col_info = st.columns([1, 3])
                with col_mount:
                    if st.button("🔌 Monter le répertoire", key="btn_mount"):
                        try:
                            _res = _sp.run(
                                ["sudo", "mount", str(_mount_path)],
                                capture_output=True, text=True, timeout=15,
                            )
                            if _res.returncode == 0 and source_available():
                                st.success("Montage réussi.")
                                st.rerun()
                            else:
                                _err = _res.stderr.strip() or "Erreur inconnue."
                                st.error(f"Échec du montage : {_err}")
                                st.info("Vérifiez que `/etc/fstab` est configuré (voir README) et que vous êtes connecté au réseau.")
                        except _sp.TimeoutExpired:
                            st.error("Timeout — le serveur réseau ne répond pas.")
                        except Exception as _exc:
                            st.error(f"Erreur : {_exc}")

                with col_info:
                    st.info(
                        "Le montage automatique nécessite que `/etc/fstab` soit configuré "
                        "(voir README > *Montage automatique au démarrage WSL*). "
                        "Sinon, exécutez manuellement dans un terminal :\n\n"
                        "```bash\n"
                        "sudo mount -t drvfs "
                        r"'\\sv61file0024\Bureautique\Direction des Risques\'"
                        " /mnt/risques\n```"
                    )

            st.markdown("---")
            st.markdown("### Mise à jour des données")

            if not _source_ok:
                st.button("🔄 Rafraîchir les données", disabled=True, key="btn_refresh_data")
            else:
                if st.button("🔄 Rafraîchir les données", key="btn_refresh_data"):
                    _log_lines: list[str] = []

                    def _log(msg: str):
                        _log_lines.append(msg)

                    with st.spinner("Mise à jour en cours…"):
                        _results = refresh_all(
                            log=_log,
                            source_dir=_cfg.get("source_dir"),
                            backup=_cfg.get("backup_enabled", False),
                            backup_keep=_cfg.get("backup_keep", 5),
                        )

                    _errors = [n for n, r in _results.items() if r["status"] == "error"]
                    _ok     = [n for n, r in _results.items() if r["status"] == "ok"]

                    if _errors:
                        st.error(f"Échec pour : {', '.join(_errors)}")
                        for _n in _errors:
                            st.caption(f"  • {_n} : {_results[_n].get('error', '?')}")
                    else:
                        st.success(f"Mise à jour réussie — {len(_ok)} fichier(s) traité(s).")
                        # Vider le cache Streamlit pour que les nouvelles données soient prises en compte
                        st.cache_data.clear()
                        st.info("Le cache a été vidé. Rechargez la page pour voir les nouvelles données.")

                    with st.expander("Journal de mise à jour"):
                        st.text("\n".join(_log_lines))

            # ── Backups existants ─────────────────────────────────────────────
            from refresh_data import BACKUP_DIR  # type: ignore
            st.markdown("---")
            st.markdown("### 💾 Sauvegardes")

            if not BACKUP_DIR.exists() or not any(BACKUP_DIR.glob("*.csv")):
                st.info("Aucun backup disponible. Activez les sauvegardes automatiques dans Admin > Paramètres.")
            else:
                _bak_rows = []
                for _bak in sorted(BACKUP_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
                    _bs = _bak.stat()
                    _bak_rows.append({
                        "Fichier":  _bak.name,
                        "Date":     _dt.datetime.fromtimestamp(_bs.st_mtime).strftime("%d/%m/%Y %H:%M"),
                        "Taille":   (
                            f"{_bs.st_size / 1024**2:.2f} Mo" if _bs.st_size >= 1024**2
                            else f"{_bs.st_size / 1024:.1f} Ko"
                        ),
                    })
                st.dataframe(pd.DataFrame(_bak_rows), use_container_width=True, hide_index=True)
                st.caption(f"{len(_bak_rows)} backup(s) — dossier : `{BACKUP_DIR}`")

        with admin_params_tab:
            st.markdown("### Paramètres de l'application")

            _p = st.session_state["app_config"].copy()

            _col_form, _ = st.columns([1.5, 1])

            with _col_form:
                # ── 1. Sécurité ───────────────────────────────────────────────
                st.markdown("#### 🔒 Sécurité")
                st.caption(f"Connecté en tant que **{_username}**. Ce formulaire change votre mot de passe de connexion.")
                with st.form("form_password"):
                    _new_mdp1 = st.text_input(
                        "Nouveau mot de passe",
                        type="password",
                        placeholder="Laisser vide pour ne pas changer",
                    )
                    _new_mdp2 = st.text_input(
                        "Confirmer le mot de passe",
                        type="password",
                        placeholder="Répéter le nouveau mot de passe",
                    )
                    _submit_mdp = st.form_submit_button("💾 Enregistrer le mot de passe")

                if _submit_mdp:
                    if not _new_mdp1:
                        st.warning("Aucun nouveau mot de passe saisi.")
                    elif _new_mdp1 != _new_mdp2:
                        st.error("Les deux mots de passe ne correspondent pas.")
                    else:
                        _err_pwd = update_password(_p, _username, _new_mdp1)
                        if _err_pwd:
                            st.error(_err_pwd)
                        else:
                            save_config(_p)
                            st.session_state["app_config"] = _p
                            st.success("Mot de passe mis à jour. Reconnectez-vous avec le nouveau mot de passe.")

                st.markdown("---")

                # ── 2. Chemin source SAS ──────────────────────────────────────
                st.markdown("#### 📂 Répertoire source SAS")
                with st.form("form_source_dir"):
                    _new_source = st.text_input(
                        "Chemin du répertoire source",
                        value=_p.get("source_dir", ""),
                        help="Chemin Linux vers le dossier contenant les fichiers JSON SAS",
                    )
                    _submit_src = st.form_submit_button("💾 Enregistrer le chemin")

                if _submit_src:
                    if not _new_source.strip():
                        st.error("Le chemin ne peut pas être vide.")
                    else:
                        _p["source_dir"] = _new_source.strip()
                        save_config(_p)
                        st.session_state["app_config"] = _p
                        st.success("Chemin source mis à jour.")
                        if not Path(_new_source.strip()).exists():
                            st.warning("Attention : ce chemin n'est pas accessible actuellement.")

                st.markdown("---")

                # ── 3. Seuil de surbrillance VaR 99% ─────────────────────────
                st.markdown("#### 📊 Seuil de surbrillance VaR 99%")
                st.caption(
                    "Les titres dont la VaR 99% dépasse ce percentile sont surlignés en rouge "
                    "dans le Détail par titre (Risque Taux)."
                )
                _quantile_options = {
                    "Q1 — 25e percentile (très sensible)" : 0.25,
                    "Médiane — 50e percentile"            : 0.50,
                    "Q3 — 75e percentile (défaut)"        : 0.75,
                    "90e percentile (peu sensible)"       : 0.90,
                }
                _current_q = _p.get("var_quantile", 0.75)
                _current_label = next(
                    (lbl for lbl, val in _quantile_options.items() if val == _current_q),
                    "Q3 — 75e percentile (défaut)",
                )
                with st.form("form_var_quantile"):
                    _new_q_label = st.selectbox(
                        "Seuil VaR 99%",
                        options=list(_quantile_options.keys()),
                        index=list(_quantile_options.keys()).index(_current_label),
                    )
                    _submit_q = st.form_submit_button("💾 Enregistrer le seuil")

                if _submit_q:
                    _p["var_quantile"] = _quantile_options[_new_q_label]
                    save_config(_p)
                    st.session_state["app_config"] = _p
                    st.success(f"Seuil VaR mis à jour : {_new_q_label}.")

                st.markdown("---")

                # ── 4. Backups ────────────────────────────────────────────────
                st.markdown("#### 💾 Sauvegardes automatiques")
                st.caption(
                    "Si activé, le CSV actuel est copié dans `data/backups/` "
                    "avec horodatage avant chaque écrasement."
                )
                with st.form("form_backup"):
                    _backup_enabled = st.toggle(
                        "Activer les backups avant mise à jour",
                        value=_p.get("backup_enabled", False),
                    )
                    _backup_keep = st.selectbox(
                        "Backups à conserver par fichier",
                        options=[1, 3, 5, 10, 0],
                        index=[1, 3, 5, 10, 0].index(
                            _p.get("backup_keep", 5)
                            if _p.get("backup_keep", 5) in [1, 3, 5, 10, 0] else 5
                        ),
                        format_func=lambda x: f"{x} derniers" if x > 0 else "Tous (illimité)",
                    )
                    _submit_backup = st.form_submit_button("💾 Enregistrer")

                if _submit_backup:
                    _p["backup_enabled"] = _backup_enabled
                    _p["backup_keep"]    = _backup_keep
                    save_config(_p)
                    st.session_state["app_config"] = _p
                    _lbl = f"{_backup_keep} derniers" if _backup_keep > 0 else "illimité"
                    st.success(
                        f"Backups {'activés' if _backup_enabled else 'désactivés'}"
                        + (f" — conservation : {_lbl}." if _backup_enabled else ".")
                    )

                st.markdown("---")

                # ── 5. Affichage par défaut ───────────────────────────────────
                st.markdown("#### 🔢 Affichage par défaut")
                st.caption("Nombre de titres affichés par défaut dans les Détail par titre.")
                with st.form("form_top_n"):
                    _new_top_n = st.selectbox(
                        "Top N par défaut",
                        options=[10, 20, 30, 50, 100, 0],
                        index=[10, 20, 30, 50, 100, 0].index(
                            _p.get("default_top_n", 20)
                            if _p.get("default_top_n", 20) in [10, 20, 30, 50, 100, 0] else 20
                        ),
                        format_func=lambda x: f"Top {x}" if x > 0 else "Tous les titres",
                    )
                    _submit_n = st.form_submit_button("💾 Enregistrer")

                if _submit_n:
                    _p["default_top_n"] = _new_top_n
                    save_config(_p)
                    st.session_state["app_config"] = _p
                    st.success(f"Top N par défaut mis à jour : {'Tous' if _new_top_n == 0 else _new_top_n}.")

        with admin_diag_tab:
            import platform as _platform
            import datetime as _dt_diag
            import importlib.metadata as _imeta
            from refresh_data import _build_fichiers, _get_source_dir  # type: ignore

            st.markdown("### Diagnostics")

            _dcol1, _dcol2 = st.columns(2)

            # ── 1. Environnement ──────────────────────────────────────────────
            with _dcol1:
                st.markdown("#### 🖥️ Environnement")

                def _pkg_version(name: str) -> str:
                    try:
                        return _imeta.version(name)
                    except Exception:
                        return "—"

                _env_rows = [
                    {"Composant": "Python",     "Version": _platform.python_version()},
                    {"Composant": "Streamlit",  "Version": _pkg_version("streamlit")},
                    {"Composant": "pandas",     "Version": _pkg_version("pandas")},
                    {"Composant": "plotly",     "Version": _pkg_version("plotly")},
                    {"Composant": "numpy",      "Version": _pkg_version("numpy")},
                    {"Composant": "openpyxl",   "Version": _pkg_version("openpyxl")},
                    {"Composant": "OS",         "Version": _platform.system() + " " + _platform.release()},
                ]
                st.dataframe(pd.DataFrame(_env_rows), use_container_width=True, hide_index=True)

            # ── 2. Session courante ───────────────────────────────────────────
            with _dcol2:
                st.markdown("#### 🔍 Session courante")

                _d_debut_str = date_debut.strftime("%d/%m/%Y") if hasattr(date_debut, "strftime") else str(date_debut)
                _d_fin_str   = date_fin.strftime("%d/%m/%Y")   if hasattr(date_fin,   "strftime") else str(date_fin)

                _sess_rows = [
                    {"Paramètre": "Source",          "Valeur": "Base Transpa" if use_transpa else "Base Parent"},
                    {"Paramètre": "Portefeuille",    "Valeur": portefeuil},
                    {"Paramètre": "Cantons actifs",  "Valeur": ", ".join(canton) if canton else "—"},
                    {"Paramètre": "Date début",      "Valeur": _d_debut_str},
                    {"Paramètre": "Date fin",        "Valeur": _d_fin_str},
                    {"Paramètre": "Lignes sélect.",  "Valeur": f"{len(df_selection):,}".replace(",", " ")},
                    {"Paramètre": "Colonnes",        "Valeur": str(len(df_selection.columns))},
                ]
                st.dataframe(pd.DataFrame(_sess_rows), use_container_width=True, hide_index=True)

            st.markdown("---")

            # ── 3. État des fichiers de données ───────────────────────────────
            st.markdown("#### 📂 État des fichiers CSV")

            _diag_fichiers = _build_fichiers(_get_source_dir(_cfg.get("source_dir")))
            _file_rows = []
            for _fname, _fcfg in _diag_fichiers.items():
                _csv = _fcfg["cleaned"]
                if _csv.exists():
                    _st   = _csv.stat()
                    _mtime = _dt_diag.datetime.fromtimestamp(_st.st_mtime).strftime("%d/%m/%Y %H:%M")
                    _sz    = _st.st_size
                    _sz_str = (
                        f"{_sz / 1024**2:.2f} Mo" if _sz >= 1024**2
                        else f"{_sz / 1024:.1f} Ko" if _sz >= 1024
                        else f"{_sz} o"
                    )
                    try:
                        _nl = sum(1 for _ in open(_csv, encoding="utf-8-sig")) - 1
                        _nl_str = f"{_nl:,}".replace(",", " ")
                    except Exception:
                        _nl_str = "—"
                    _etat = "✅ OK"
                else:
                    _mtime = "—"
                    _sz_str = "—"
                    _nl_str = "—"
                    _etat = "⚠️ Absent"

                _file_rows.append({
                    "Fichier":       _csv.name,
                    "Dernière MAJ":  _mtime,
                    "Taille":        _sz_str,
                    "Lignes":        _nl_str,
                    "État":          _etat,
                })

            st.dataframe(pd.DataFrame(_file_rows), use_container_width=True, hide_index=True)

            # Statut du montage réseau
            _src_path = Path(_cfg.get("source_dir", "/mnt/risques"))
            if _src_path.exists():
                st.success(f"Répertoire source accessible : `{_src_path}`")
            else:
                st.error(f"Répertoire source inaccessible : `{_src_path}`")

            st.markdown("---")

            # ── 4. Cache ──────────────────────────────────────────────────────
            st.markdown("#### 🗑️ Cache Streamlit")
            st.caption("Vider le cache force le rechargement complet des données au prochain rerun.")
            if st.button("🗑️ Vider le cache", key="btn_clear_cache_diag"):
                st.cache_data.clear()
                st.cache_resource.clear()
                st.success("Cache vidé. Les données seront rechargées au prochain rerun.")

        with admin_users_tab:
            st.markdown("### Utilisateurs / Accès")
            st.caption(
                "Les comptes ci-dessous sont enregistrés localement. "
                "Les rôles sont indicatifs — le contrôle d'accès complet sera activé dans une prochaine version."
            )

            _up = st.session_state["app_config"]

            # ── Tableau des utilisateurs ──────────────────────────────────────
            st.markdown("#### 👥 Comptes enregistrés")

            _users = get_users(_up)
            _role_badge = {"Admin": "🔴", "Analyste": "🟡", "Lecteur": "🟢"}
            _user_rows = [
                {
                    "Utilisateur": u["username"],
                    "Rôle":        f"{_role_badge.get(u['role'], '')} {u['role']}",
                    "Statut":      "✅ Actif" if u["active"] else "⛔ Inactif",
                }
                for u in _users
            ]
            st.dataframe(pd.DataFrame(_user_rows), use_container_width=True, hide_index=True)

            _ucol1, _ucol2 = st.columns(2)

            # ── Ajouter un utilisateur ────────────────────────────────────────
            with _ucol1:
                st.markdown("#### ➕ Ajouter un utilisateur")
                with st.form("form_add_user"):
                    _new_uname = st.text_input("Nom d'utilisateur", key="add_u_name")
                    _new_urole = st.selectbox("Rôle", options=ROLES, index=0, key="add_u_role")
                    _new_upwd1 = st.text_input("Mot de passe", type="password", key="add_u_pwd1")
                    _new_upwd2 = st.text_input("Confirmer le mot de passe", type="password", key="add_u_pwd2")
                    _submit_add = st.form_submit_button("➕ Ajouter")

                if _submit_add:
                    if _new_upwd1 != _new_upwd2:
                        st.error("Les mots de passe ne correspondent pas.")
                    else:
                        _err = add_user(_up, _new_uname, _new_urole, _new_upwd1)
                        if _err:
                            st.error(_err)
                        else:
                            save_config(_up)
                            st.session_state["app_config"] = _up
                            st.success(f"Utilisateur « {_new_uname} » ajouté ({_new_urole}).")
                            st.rerun()

            # ── Actions sur un utilisateur existant ───────────────────────────
            with _ucol2:
                st.markdown("#### ✏️ Gérer un utilisateur")
                _unames = [u["username"] for u in _users]
                _sel_user = st.selectbox("Sélectionner un utilisateur", options=_unames, key="sel_manage_user")
                _sel_data = next((u for u in _users if u["username"] == _sel_user), None)

                if _sel_data:
                    st.markdown(
                        f"**Rôle :** {_sel_data['role']} &nbsp;|&nbsp; "
                        f"**Statut :** {'✅ Actif' if _sel_data['active'] else '⛔ Inactif'}",
                        unsafe_allow_html=True,
                    )

                    # Activer / désactiver
                    _btn_lbl = "⛔ Désactiver" if _sel_data["active"] else "✅ Activer"
                    if st.button(_btn_lbl, key="btn_toggle_user"):
                        set_user_active(_up, _sel_user, not _sel_data["active"])
                        save_config(_up)
                        st.session_state["app_config"] = _up
                        st.rerun()

                    # Changer le rôle
                    with st.form("form_change_role"):
                        _new_role = st.selectbox(
                            "Changer le rôle",
                            options=ROLES,
                            index=ROLES.index(_sel_data["role"]) if _sel_data["role"] in ROLES else 0,
                        )
                        _submit_role = st.form_submit_button("💾 Enregistrer le rôle")

                    if _submit_role:
                        _sel_data["role"] = _new_role
                        save_config(_up)
                        st.session_state["app_config"] = _up
                        st.success(f"Rôle mis à jour : {_new_role}.")
                        st.rerun()

                    # Changer le mot de passe
                    with st.form("form_change_pwd"):
                        _chg_pwd1 = st.text_input("Nouveau mot de passe", type="password")
                        _chg_pwd2 = st.text_input("Confirmer", type="password")
                        _submit_pwd = st.form_submit_button("🔑 Changer le mot de passe")

                    if _submit_pwd:
                        if _chg_pwd1 != _chg_pwd2:
                            st.error("Les mots de passe ne correspondent pas.")
                        else:
                            _err = update_password(_up, _sel_user, _chg_pwd1)
                            if _err:
                                st.error(_err)
                            else:
                                save_config(_up)
                                st.session_state["app_config"] = _up
                                st.success("Mot de passe mis à jour.")

                    # Supprimer
                    st.markdown("---")
                    if _sel_user != "admin":
                        if st.button("🗑️ Supprimer cet utilisateur", key="btn_del_user"):
                            _err = delete_user(_up, _sel_user)
                            if _err:
                                st.error(_err)
                            else:
                                save_config(_up)
                                st.session_state["app_config"] = _up
                                st.success(f"Utilisateur « {_sel_user} » supprimé.")
                                st.rerun()
                    else:
                        st.caption("L'utilisateur admin principal ne peut pas être supprimé.")