import streamlit as st
from db.loader import load_table


@st.cache_data(show_spinner=False)
def _load(name: str):
    return load_table(name)


# DataFrames exposés à home.py et aux modules via `from data import *`
df_parent  = _load("base_parent")
df_transpa = _load("base_transpa")
