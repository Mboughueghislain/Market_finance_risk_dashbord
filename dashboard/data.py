import streamlit as st
from db.loader import load_table


@st.cache_data(show_spinner=False)
def load_df(name: str):
    """
    Charge un DataFrame par son nom logique (ex: "base_parent", "base_transpa").
    Résultat mis en cache — invalidé par st.cache_data.clear().
    Appelé à chaque rerun depuis home.py pour que le cache soit réévalué après un refresh.
    """
    return load_table(name)
