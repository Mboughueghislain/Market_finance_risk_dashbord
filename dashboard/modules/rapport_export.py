# dashboard/modules/rapport_export.py

import io
import re
from typing import List, Dict, Optional

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
import pandas as pd
import plotly.io as pio  
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak
)
from modules.format_utils import fmt_meur, fmt_delta_meur, fmt_bp, fmt_pct, apply_common_table_styles
from reportlab.lib.styles import getSampleStyleSheet


# ====== PALETTE GLOBALE ======
MAIN_PURPLE_HEX = "#714A80"
TREND_UP_HEX = "#008000"      # vert
TREND_DOWN_HEX = "#D62728"    # rouge
TREND_STABLE_HEX = "#555555"  # gris

# ==========================
# Helpers
# ==========================
# === Helpers figures pour le PDF ============================================
def is_heavy_figure(fig) -> bool:
    """
    Retourne True uniquement pour les treemaps (figures non exportables par kaleido).
    Les cartes géographiques sont maintenant exportées normalement.
    """
    if fig is None:
        return False

    trace_types = {getattr(tr, "type", None) for tr in getattr(fig, "data", [])}

    if "treemap" in trace_types:
        return True

    return False


def fig_to_png_for_pdf(fig, width: int = 700, height: int = 320, scale: int = 1) -> Optional[bytes]:
    """
    Convertit une figure Plotly en PNG pour le PDF.
    Retourne None uniquement si la figure est un treemap ou en cas d'erreur kaleido.
    """
    if fig is None:
        return None

    if is_heavy_figure(fig):
        print("[rapport_export] fig_to_png_for_pdf: treemap -> placeholder")
        return None

    try:
        print("[rapport_export] fig_to_png_for_pdf: export PNG OK –", type(fig))
        return pio.to_image(
            fig,
            format="png",
            width=width,
            height=height,
            scale=scale,
            engine="kaleido",
        )
    except Exception as e:
        print("[rapport_export] fig_to_png_for_pdf: ERREUR export –", repr(e))
        return None

def fig_to_png_bytes(
    fig,
    width: int = 1000,
    height: int = 480,
    scale: float = 1.5,
):
    """
    Convertit une figure Plotly en image PNG (bytes) pour le PDF.
    - Force fond blanc (paper_bgcolor + plot_bgcolor) pour éviter les fonds sombres.
    - Retourne None si la figure est None ou en cas d'erreur.
    """
    if fig is None:
        print("[rapport_export] fig_to_png_bytes: fig is None")
        return None

    print("[rapport_export] Export Plotly figure via kaleido:", type(fig))
    try:
        import plotly.graph_objects as go
        fig_export = go.Figure(fig.to_dict())
        fig_export.update_layout(
            paper_bgcolor="white",
            plot_bgcolor="white",
            font_color="#333333",
        )

        # Pour les cartes géographiques : fitbounds="locations" peut bloquer kaleido
        # → on le désactive pour l'export statique
        trace_types = {getattr(tr, "type", None) for tr in getattr(fig_export, "data", [])}
        is_geo = bool(trace_types & {"scattergeo", "choropleth", "choroplethmapbox"})
        if is_geo:
            fig_export.update_geos(fitbounds=False)

        return pio.to_image(
            fig_export,
            format="png",
            width=width,
            height=height,
            scale=scale,
            engine="kaleido",
        )
    except Exception as e:
        print("[rapport_export] Erreur fig_to_png_bytes:", repr(e))
        return None
    

def _add_placeholder_capture(story, label: str = "Zone capture d'écran"):
    """
    Ajoute un bloc placeholder dans le PDF pour indiquer
    où coller un screenshot manuellement si le graphe n'a
    pas pu être généré.
    """

    placeholder_tbl = Table(
        [[label]],
        colWidths=[16 * cm],
        rowHeights=[5 * cm],
        hAlign="CENTER",
    )
    placeholder_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(placeholder_tbl)
    story.append(Spacer(1, 0.4 * cm))
    
def _figure_export_params(fig):
    """
    Choisit (width, height, scale) pour l'export PNG des figures Plotly.
    Simple, rapide et stable (optimisé PDF).
    """
    # Valeurs par défaut (rapides)
    width = 900
    height = 420
    scale = 1

    try:
        trace_types = {getattr(t, "type", None) for t in fig.data}

        # Treemap → plus compact
        if "treemap" in trace_types:
            return 700, 360, 1

        # Cartes (geo / mapbox)
        if (
            "scattergeo" in trace_types
            or "choropleth" in trace_types
            or hasattr(fig.layout, "geo")
            or hasattr(fig.layout, "mapbox")
        ):
            return 900, 480, 1

    except Exception:
        pass

    return width, height, scale

def _format_df_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    Applique un formatage TEXTE proche de celui des tableaux Streamlit :

      - colonnes en M€ -> fmt_meur
      - colonnes Δ VM (M€) -> fmt_delta_meur
      - colonnes en % -> fmt_pct
      - colonnes en bp -> fmt_bp
      - colonne Tendance : on supprime les pictos (carrés, triangles),
        on ne garde que 'hausse / baisse / stable'.

    On retourne un DF de chaînes de caractères (prêt pour ReportLab ).
    """
    df2 = df.copy()

    for col in df2.columns:
        col_name = str(col)
        series = df2[col]

        def _none_if_nan(x: float, fn) -> str:
            if pd.isna(x):
                return ""
            return fn(x)

        # === Colonnes montants en M€ ===================================
        # - tout ce qui contient 'M€' dans le libellé
        # - plus quelques noms "spéciaux" : Mandats / Direct hors OPC / Total
        if (
            "Valeur de Marché" in col_name
            or "M€" in col_name
            or col_name in ("Mandats", "Direct hors OPC", "Total")
        ):
            if pd.api.types.is_numeric_dtype(series):
                df2[col] = series.apply(lambda x: _none_if_nan(x, fmt_meur))
            else:
                df2[col] = series.astype(str)

        # === Δ VM (M€) ================================================
        elif "Δ VM (M€" in col_name or "Delta_VM" in col_name:
            if pd.api.types.is_numeric_dtype(series):
                df2[col] = series.apply(lambda x: _none_if_nan(x, fmt_delta_meur))
            else:
                df2[col] = series.astype(str)

        # === Colonnes en % ============================================
        elif "(%)" in col_name or "Poids portefeuille" in col_name:
            if pd.api.types.is_numeric_dtype(series):
                df2[col] = series.apply(lambda x: _none_if_nan(x, fmt_pct))
            else:
                df2[col] = series.astype(str)

        # === Spread en bp =============================================
        elif "Spread (bp)" in col_name or "bp" in col_name:
            if pd.api.types.is_numeric_dtype(series):
                df2[col] = series.apply(lambda x: _none_if_nan(x, fmt_bp))
            else:
                df2[col] = series.astype(str)

        # === Autres colonnes numériques ===============================
        elif pd.api.types.is_numeric_dtype(series):
            df2[col] = series.apply(
                lambda x: "" if pd.isna(x) else format(float(x), ",.2f")
            )

        # === Texte / catégories =======================================
        else:
            df2[col] = series.astype(str)

    # On conserve les symboles ▲▼◆ dans la colonne Tendance
    # (DejaVuSans est enregistré dans rapport_pdf_V2.py pour les rendre)

    return df2

def _truncate_with_total(df: pd.DataFrame, max_rows: int = 12) -> pd.DataFrame:
    """
    Tronque le DF à max_rows lignes, en s'assurant que la/les ligne(s) contenant 'TOTAL'
    soient conservées dans le résultat.
    """
    if len(df) <= max_rows:
        return df.copy()

    df = df.copy()
    # repère les lignes qui contiennent "TOTAL" dans au moins une cellule
    mask_total = df.apply(
        lambda row: any(str(v).strip().upper() == "TOTAL" for v in row),
        axis=1,
    )

    if not mask_total.any():
        return df.head(max_rows)

    df_total = df[mask_total]
    df_main = df[~mask_total].head(max_rows - len(df_total))

    return pd.concat([df_main, df_total], axis=0)

# ==========================
# Sélection des figures exportables
# ==========================

def is_exportable_figure(fig) -> bool:
    """
    Retourne True si la figure Plotly peut être exportée dans le rapport PDF.

    On exclut volontairement :
      - les treemap
      - les cartes (scattergeo / choropleth / mapbox)
    pour accélérer la génération du PDF.
    """
    if fig is None:
        return False

    # Doit contenir au moins une trace
    data = getattr(fig, "data", None)
    if not data:
        return False

    trace_types = {getattr(tr, "type", None) for tr in data}

    heavy_traces = {
        ""
    }

    # Si la figure contient un de ces types → on ne l'exporte pas
    if trace_types & heavy_traces:
        return False

    return True


# Helper : conversion Plotly -> PNG (pour le PDF)
def fig_to_png_for_pdf(fig):
    """
    Renvoie les bytes PNG d'une figure Plotly pour le PDF,
    ou None si la figure est None ou en cas d'erreur.
    """
    if fig is None:
        return None

    # Option : un peu de log pour suivre dans la console
    trace_types = {getattr(tr, "type", None) for tr in getattr(fig, "data", [])}
    print("[rapport] fig_to_png_for_pdf: trace_types =", trace_types)

    # Taille standard pour le PDF
    width = 700
    height = 320
    scale = 1

    # On délègue à la fonction utilitaire du module rapport_export
    from modules.rapport_export import fig_to_png_bytes

    return fig_to_png_bytes(fig, width=width, height=height, scale=scale)

# ==========================
# PDF (ReportLab)
# ==========================

def build_full_pdf_report(sections: List[Dict], periode_label: str) -> bytes:
    """
    Construit un PDF avec :
      - page de garde
      - 1 page par section :
          * titre
          * sous-titre + période
          * image PNG (0, 1 ou 2) SI dispo dans section["figures_png"]
          * SINON : un bloc "zone de capture d'écran"
          * tableau (max ~12 lignes, TOTAL conservé) avec hauteur harmonisée
          * bloc 'Analyse :' + commentaire texte
    IMPORTANT :
      - Cette fonction NE FAIT PLUS aucune conversion Plotly -> PNG.
        Elle consomme UNIQUEMENT des bytes PNG pré-calculés dans Streamlit.
    """

    # ========= 1) Préparation des tableaux (pour harmoniser la hauteur) =========
    prepared_sections = []
    max_table_rows = 0  # nombre max de lignes (header compris) parmi toutes les sections

    for sec in sections:
        df: pd.DataFrame = sec.get("table")
        df_export = None
        nrows_export = 0

        if df is not None and not df.empty:
            # On tronque / formate ici UNE SEULE FOIS
            df_trunc = _truncate_with_total(df, max_rows=12)
            df_trunc = _format_df_for_export(df_trunc)
            df_export = df_trunc
            nrows_export = len(df_trunc) + 1  # +1 pour l'en-tête

            if nrows_export > max_table_rows:
                max_table_rows = nrows_export

        prepared_sections.append(
            {
                **sec,
                "_table_export": df_export,
                "_table_nrows": nrows_export,
            }
        )

    # Si on a au moins un tableau, on fixe une hauteur "cible" globale
    base_row_height = 0.55 * cm  # hauteur de base d'une ligne
    target_table_height = max_table_rows * base_row_height if max_table_rows > 0 else None

    # ========= 2) Construction du PDF ReportLab =========
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    if "CenterTitle" not in styles:
        styles.add(
            ParagraphStyle(
                name="CenterTitle",
                parent=styles["Title"],
                alignment=TA_CENTER,
            )
        )
    if "CenterHeading2" not in styles:
        styles.add(
            ParagraphStyle(
                name="CenterHeading2",
                parent=styles["Heading2"],
                alignment=TA_CENTER,
            )
        )
    if "CenterNormal" not in styles:
        styles.add(
            ParagraphStyle(
                name="CenterNormal",
                parent=styles["Normal"],
                alignment=TA_CENTER,
            )
        )

    story = []

    # ---------- Page de garde ----------
    story.append(
        Paragraph("<b>Rapport commenté – Risques financiers</b>", styles["CenterTitle"])
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"Période : {periode_label}", styles["CenterNormal"]))
    story.append(Spacer(1, 1.2 * cm))

    # ---------- Sections ----------
    for idx, sec in enumerate(prepared_sections):
        if idx > 0:
            story.append(PageBreak())

        title = sec.get("title", "")
        subtitle = sec.get("subtitle", "")
        df_export: Optional[pd.DataFrame] = sec.get("_table_export")
        nrows_export: int = sec.get("_table_nrows", 0)
        figures_png = sec.get("figures_png") or []   # liste de bytes PNG (0, 1 ou 2)
        comment = sec.get("comment", "")

        # --- Titre section ---
        story.append(Paragraph(f"<b>{title}</b>", styles["CenterHeading2"]))
        story.append(Spacer(1, 0.1 * cm))
        story.append(
            Paragraph(f"{subtitle} – {periode_label}", styles["CenterNormal"])
        )
        story.append(Spacer(1, 0.4 * cm))

        # --- FIGURE(S) (0, 1 ou 2) ----------------------------------
        # 1) On commence par regarder si la section fournit des PNG prêts à l'emploi
        figures_png = sec.get("figures_png")
        # si on a des bytes pré-calculés, on les utilise en priorité
        figures_bytes = sec.get("figures_png") or sec.get("figures_bytes")

        if figures_bytes:
            # on enlève les None éventuels
            figures_bytes = [b for b in figures_bytes if b is not None]
        else:
            figures_bytes = []

        figures = []

        # 2) Si on n'a pas reçu de PNG, on retombe sur le comportement Plotly classique
        if not figures_bytes:
            if sec.get("figures") is not None:
                for f in sec.get("figures", []):
                    if is_exportable_figure(f):
                        figures.append(f)
            else:
                f = sec.get("figure")
                if is_exportable_figure(f):
                    figures.append(f)

        # ========================================================
        # Cas A : on a des BYTES -> on construit directement les images
        # ========================================================
        if figures_bytes:
            if len(figures_bytes) == 1:
                # une seule image -> centrée
                try:
                    img = Image(io.BytesIO(figures_bytes[0]))
                    img._restrictSize(17 * cm, 7 * cm)
                    story.append(img)
                    story.append(Spacer(1, 0.4 * cm))
                except Exception as e:
                    print("[PDF] Erreur lors de l'utilisation du PNG:", repr(e))
                    _add_placeholder_capture(story)

            elif len(figures_bytes) >= 2:
                # deux images -> côte à côte
                imgs_row = []
                for b in figures_bytes[:2]:
                    try:
                        img = Image(io.BytesIO(b))
                        img._restrictSize(8.2 * cm, 6.0 * cm)
                        imgs_row.append(img)
                    except Exception as e:
                        print("[PDF] Erreur sur un PNG (multi):", repr(e))

                if imgs_row:
                    t = Table([imgs_row], colWidths=[8.2 * cm] * len(imgs_row))
                    t.setStyle(TableStyle([]))  # pas de grille
                    story.append(t)
                    story.append(Spacer(1, 0.4 * cm))
                else:
                    _add_placeholder_capture(story)

        # ========================================================
        # Cas B : pas de bytes, on revient au comportement Plotly
        # ========================================================
        elif len(figures) == 1:
            fig = figures[0]
            print(f"[PDF] Export d'une figure pour la section: {title!r}")
            width, height, scale = _figure_export_params(fig)
            try:
                img_bytes = fig_to_png_bytes(
                    fig,
                    width=width,
                    height=height,
                    scale=scale,
                )
            except Exception as e:
                print("[PDF] Erreur fig_to_png_bytes pour", repr(title), ":", repr(e))
                img_bytes = None

            if img_bytes:
                try:
                    img = Image(io.BytesIO(img_bytes))
                    img._restrictSize(17 * cm, 7 * cm)
                    story.append(img)
                    story.append(Spacer(1, 0.4 * cm))
                except Exception as e:
                    print("[PDF] Erreur lors de l'ajout de l'image:", repr(e))
                    _add_placeholder_capture(story)
            else:
                print("[PDF] Aucune image générée pour", repr(title))
                _add_placeholder_capture(story)

        elif len(figures) >= 2:
            print(f"[PDF] Export de deux figures côte à côte pour la section: {title!r}")
            imgs_row = []
            for f in figures[:2]:
                width, height, scale = _figure_export_params(f)
                try:
                    img_bytes = fig_to_png_bytes(
                        f,
                        width=width,
                        height=height,
                        scale=scale,
                    )
                except Exception as e:
                    print("[PDF] Erreur fig_to_png_bytes (multi) pour", repr(title), ":", repr(e))
                    img_bytes = None

                if img_bytes:
                    try:
                        img = Image(io.BytesIO(img_bytes))
                        img._restrictSize(8.2 * cm, 6.0 * cm)
                        imgs_row.append(img)
                    except Exception as e:
                        print("[PDF] Erreur ajout image (multi):", repr(e))

            if imgs_row:
                t = Table([imgs_row], colWidths=[8.2 * cm] * len(imgs_row))
                t.setStyle(TableStyle([]))  # pas de grille
                story.append(t)
                story.append(Spacer(1, 0.4 * cm))
            else:
                print("[PDF] Aucune image générée dans le mode 2 figures.")
                _add_placeholder_capture(story)

        else:
            # Aucun graphique pour cette section -> placeholder
            _add_placeholder_capture(story)
        # --- TABLEAU (si dispo) ---
        if df_export is not None and not df_export.empty:
            # Données pour ReportLab (df_export est déjà tronqué et formaté)
            data = [list(df_export.columns)] + df_export.astype(str).values.tolist()

            # Même LARGEUR pour tous les tableaux : 17 cm
            ncols = len(df_export.columns)
            if ncols == 0:
                continue

            col_widths = [17 * cm / ncols] * ncols

            table = Table(data, colWidths=col_widths, hAlign="CENTER")

            base_style = [
                # En-tête violet
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(MAIN_PURPLE_HEX)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                # Grille + taille de police
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
            ]

            # ----- Colonne Tendance : couleur de texte -----
            trend_col_idx = None
            for j, col_name in enumerate(df_export.columns):
                if "TENDANCE" in str(col_name).upper():
                    trend_col_idx = j
                    break

            if trend_col_idx is not None:
                for row_idx, row in enumerate(df_export.itertuples(index=False), start=1):
                    txt = str(row[trend_col_idx]).strip().upper()
                    if "HAUSSE" in txt:
                        color = colors.green
                    elif "BAISSE" in txt:
                        color = colors.red
                    elif "STABLE" in txt:
                        color = colors.HexColor(TREND_STABLE_HEX)
                    else:
                        continue
                    base_style.append(
                        (
                            "TEXTCOLOR",
                            (trend_col_idx, row_idx),
                            (trend_col_idx, row_idx),
                            color,
                        )
                    )

            # ----- Lignes TOTAL en violet -----
            for row_idx, row in enumerate(df_export.itertuples(index=False), start=1):
                row_vals = [str(v).strip().upper() for v in row]
                if "TOTAL" in row_vals:
                    base_style.extend(
                        [
                            (
                                "BACKGROUND",
                                (0, row_idx),
                                (-1, row_idx),
                                colors.HexColor(MAIN_PURPLE_HEX),
                            ),
                            (
                                "TEXTCOLOR",
                                (0, row_idx),
                                (-1, row_idx),
                                colors.white,
                            ),
                            (
                                "FONTNAME",
                                (0, row_idx),
                                (-1, row_idx),
                                "Helvetica-Bold",
                            ),
                        ]
                    )

            table.setStyle(TableStyle(base_style))
            story.append(table)
            story.append(Spacer(1, 0.4 * cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def build_full_pdf_report_text_only(sections: List[Dict], periode_label: str) -> bytes:
    """
    Version simplifiée du rapport PDF :
    - page de garde
    - 1 page par section
        * titre
        * sous-titre + période
        * placeholder "zone graphique"
        * tableau tronqué
        * bloc "Analyse :" + commentaire
    -> AUCUNE génération de figure / PNG
    """

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    if "CenterTitle" not in styles:
        styles.add(
            ParagraphStyle(
                name="CenterTitle",
                parent=styles["Title"],
                alignment=TA_CENTER,
            )
        )
    if "CenterHeading2" not in styles:
        styles.add(
            ParagraphStyle(
                name="CenterHeading2",
                parent=styles["Heading2"],
                alignment=TA_CENTER,
            )
        )
    if "CenterNormal" not in styles:
        styles.add(
            ParagraphStyle(
                name="CenterNormal",
                parent=styles["Normal"],
                alignment=TA_CENTER,
            )
        )

    story = []

    # ---------- Page de garde ----------
    story.append(
        Paragraph("<b>Rapport commenté – Risques financiers</b>", styles["CenterTitle"])
    )
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(f"Période : {periode_label}", styles["CenterNormal"]))
    story.append(Spacer(1, 1.5 * cm))

    # ---------- Sections ----------
    for idx, sec in enumerate(sections):
        if idx > 0:
            story.append(PageBreak())

        title = sec.get("title", "")
        subtitle = sec.get("subtitle", "")
        df: pd.DataFrame = sec.get("table")
        comment = sec.get("comment", "")

        # --- Titre section ---
        story.append(Paragraph(f"<b>{title}</b>", styles["CenterHeading2"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            Paragraph(f"{subtitle} – {periode_label}", styles["CenterNormal"])
        )
        story.append(Spacer(1, 0.5 * cm))

        # --- Placeholder graphique ---
        placeholder_table = Table(
            [["Zone graphique (non générée)"]],
            colWidths=[16 * cm],
            rowHeights=[4 * cm],
        )
        placeholder_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ]
            )
        )
        story.append(placeholder_table)
        story.append(Spacer(1, 0.5 * cm))

        # --- TABLEAU (si dispo) ---
        if df is not None and not df.empty:
            max_rows = min(len(df), 12)
            df_trunc = _truncate_with_total(df, max_rows=max_rows)
            df_trunc = _format_df_for_export(df_trunc)

            data = [list(df_trunc.columns)] + df_trunc.astype(str).values.tolist()
            table = Table(data, hAlign="CENTER")

            base_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(MAIN_PURPLE_HEX)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
            ]

            # Lignes TOTAL en violet
            for row_idx, row in enumerate(df_trunc.itertuples(index=False), start=1):
                row_vals = [str(v).strip().upper() for v in row]
                if "TOTAL" in row_vals:
                    base_style.extend(
                        [
                            (
                                "BACKGROUND",
                                (0, row_idx),
                                (-1, row_idx),
                                colors.HexColor(MAIN_PURPLE_HEX),
                            ),
                            (
                                "TEXTCOLOR",
                                (0, row_idx),
                                (-1, row_idx),
                                colors.white,
                            ),
                            (
                                "FONTNAME",
                                (0, row_idx),
                                (-1, row_idx),
                                "Helvetica-Bold",
                            ),
                        ]
                    )

            table.setStyle(TableStyle(base_style))
            story.append(table)
            story.append(Spacer(1, 0.5 * cm))

        # --- Bloc "Analyse :" + commentaire ---
        story.append(Paragraph("Analyse :", styles["Normal"]))
        story.append(Spacer(1, 1.2 * cm))

        if comment:
            story.append(Paragraph(str(comment), styles["Normal"]))
            story.append(Spacer(1, 0.6 * cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()