import streamlit as st
import pandas as pd
from typing import Optional
from modules.format_utils import df_to_excel_bytes

def tableau_data(df_selection: Optional[pd.DataFrame] = None) -> None :
    if df_selection is None:
        df_selection = st.session_state.get("df_selection")
        
    # garde-fou
    if df_selection is None or not isinstance(df_selection, pd.DataFrame):
        st.info("Aucune sélection disponible. Retournez à la page Accueil pour appliquer des filtres.")
        # Debug
        # st.write("keys: ", list(st.session_state.keys()))
        return
    # ----------Tableau----------
    st.dataframe(
        df_selection, 
        use_container_width=True,
        hide_index=True,
        )
    
    # --------------Bouton de téléchargement Excel---------------
    """excel_bytes_var = df_to_excel_bytes(
        df_selection,
        sheet_name="Data_filtrée"
    )

    st.download_button(
        label="📥 Télécharger en Excel",
        data=excel_bytes_var,
        file_name="Data_filtrée.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    """
    
    