# dashboard/utils.py
"""Utilitaires partagés entre les modules."""

from __future__ import annotations

import streamlit as st


def safe_multiselect(label: str, options: list, key: str, **kwargs):
    """
    Multiselect avec validation automatique de la session state.
    Filtre les valeurs obsolètes (ex: après switch de source de données)
    avant d'afficher le widget, évitant ainsi les StreamlitAPIException.
    """
    if key in st.session_state:
        valid = [v for v in st.session_state[key] if v in options]
        st.session_state[key] = valid
    return st.multiselect(label, options=options, key=key, **kwargs)
