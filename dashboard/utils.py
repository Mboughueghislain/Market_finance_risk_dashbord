# dashboard/utils.py
"""Utilitaires partagés entre les modules."""

from __future__ import annotations

import streamlit as st


def safe_multiselect(label: str, options: list, key: str,
                     validate_options: list | None = None, **kwargs):
    """
    Multiselect avec validation automatique de la session state.
    Filtre les valeurs obsolètes (ex: après switch de source de données)
    avant d'afficher le widget, évitant ainsi les StreamlitAPIException.

    validate_options : liste utilisée pour la validation (si différente de options).
    Utile quand les options affichées sont un sous-ensemble (ex: filtrées par classe)
    mais qu'on veut valider contre la liste complète de la source.
    """
    pool = validate_options if validate_options is not None else options
    if key in st.session_state:
        valid = [v for v in st.session_state[key] if v in pool]
        st.session_state[key] = valid
    return st.multiselect(label, options=options, key=key, **kwargs)
