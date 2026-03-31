# modules/rapport_pdf_v2.py

import io
import re
from typing import List, Dict, Optional

import pandas as pd

from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
    Flowable,
    HRFlowable,
)

# On réutilise ton formatage existant
from modules.rapport_export import _format_df_for_export, _truncate_with_total

# Enregistrement de DejaVu Sans pour le support des symboles Unicode (▲▼◆)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import platform as _platform
from pathlib import Path as _Path

def _find_font(linux_path: str, win_name: str) -> str:
    if _platform.system() == "Windows":
        p = _Path(r"C:\Windows\Fonts") / win_name
        return str(p) if p.exists() else linux_path
    return linux_path

_DEJAVU_PATH      = _find_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",      "DejaVuSans.ttf")
_DEJAVU_BOLD_PATH = _find_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf")
try:
    pdfmetrics.registerFont(TTFont("DejaVuSans", _DEJAVU_PATH))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", _DEJAVU_BOLD_PATH))
    _TABLE_FONT = "DejaVuSans"
    _TABLE_FONT_BOLD = "DejaVuSans-Bold"
except Exception:
    _TABLE_FONT = "Helvetica"
    _TABLE_FONT_BOLD = "Helvetica-Bold"

# ====== PALETTE GLOBALE ======
MAIN_PURPLE_HEX = "#714A80"
TREND_UP_HEX = "#2ca02c"      # vert  (identique format_utils.py)
TREND_DOWN_HEX = "#d62728"    # rouge (identique format_utils.py)
TREND_STABLE_HEX = "#bcbd22"  # jaune (identique format_utils.py)

# Nombre max de lignes par tableau (après troncature)
MAX_TABLE_ROWS = 12


# ----------------------------------------------------------
#  Champ de texte éditable (AcroForm) pour les commentaires
# ----------------------------------------------------------
class AnalyseTextField(Flowable):
    """
    Flowable qui rend un champ de texte éditable (formulaire PDF/AcroForm).
    Utilise relative=True pour se positionner à l'endroit où Platypus le place.
    Si 'value' est fourni (commentaire Streamlit), le champ est pré-rempli.
    Sinon, il reste vide et modifiable directement dans le lecteur PDF.
    """

    def __init__(
        self,
        field_name: str,
        value: str = "",
        width: float = 17 * cm,
        height: float = 4.0 * cm,
    ):
        Flowable.__init__(self)
        self.field_name = field_name
        self.value = value
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self):
        # Calcul des coordonnées absolues sur la page
        # (absolutePosition convertit (0,0) = bas-gauche du flowable en coordonnées PDF)
        x_abs, y_abs = self.canv.absolutePosition(0, 0)
        self.canv.acroForm.textfield(
            name=self.field_name,
            tooltip="Entrez votre commentaire ici",
            value=self.value,
            x=x_abs,
            y=y_abs,
            width=self.width,
            height=self.height,
            relative=False,
            fieldFlags="multiline",
            maxlen=0,           # 0 = pas de limite de caractères
            borderWidth=0.5,
            borderColor=colors.HexColor(MAIN_PURPLE_HEX),
            fontSize=10,
            textColor=colors.black,
            fillColor=colors.HexColor("#F8F4FC"),
        )


# ----------------------------------------------------------
#  Boîte placeholder quand il n'y a pas d'image PNG
# ----------------------------------------------------------
def _placeholder_box(
    label: str = "Capture d’écran / visuel à insérer",
    width_cm: float = 17.0,
    height_cm: float = 7.0,
) -> Table:
    data = [[label]]
    t = Table(
        data,
        colWidths=[width_cm * cm],
        rowHeights=[height_cm * cm],
        hAlign="CENTER",
    )
    t.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#666666")),
            ]
        )
    )
    return t


# ----------------------------------------------------------
#  Builder PDF v2
# ----------------------------------------------------------
def build_full_pdf_report_v2(sections: List[Dict], periode_label: str) -> bytes:
    """
    Génère un PDF à partir d'une liste de sections NORMALISÉES.

    Chaque section est un dict avec au moins :
      - "title": str
      - "subtitle": str (peut être "")
      - "table": pd.DataFrame ou None
      - "figures_png": List[bytes] (optionnel, peut être vide)
      - "comment": str (optionnel)

    IMPORTANT : ce builder n'appelle JAMAIS Plotly / Kaleido.
    Il utilise UNIQUEMENT les PNG déjà générés côté Streamlit.
    """

    buffer = io.BytesIO()

    # Numéros de page dans le pied de page
    def _add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont(_TABLE_FONT, 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        page_num = canvas.getPageNumber()
        canvas.drawRightString(
            A4[0] - 1.5 * cm, 0.8 * cm, f"Page {page_num}"
        )
        canvas.drawString(
            1.5 * cm, 0.8 * cm, "Rapport Risques Financiers — Confidentiel"
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.5 * cm,
        bottomMargin=2.0 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CoverTitle",
        fontName=_TABLE_FONT_BOLD,
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        textColor=colors.HexColor(MAIN_PURPLE_HEX),
        spaceAfter=0.4 * cm,
    ))
    styles.add(ParagraphStyle(
        name="CoverSubtitle",
        fontName=_TABLE_FONT,
        fontSize=13,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
    ))
    styles.add(ParagraphStyle(
        name="SectionTitle",
        fontName=_TABLE_FONT_BOLD,
        fontSize=14,
        leading=18,
        alignment=TA_LEFT,
        textColor=colors.HexColor(MAIN_PURPLE_HEX),
        spaceAfter=0.15 * cm,
        spaceBefore=0.1 * cm,
    ))
    styles.add(ParagraphStyle(
        name="SubSectionTitle",
        fontName=_TABLE_FONT_BOLD,
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#4a2d5a"),
        spaceAfter=0.1 * cm,
        leftIndent=0.3 * cm,
    ))
    styles.add(ParagraphStyle(
        name="PeriodLabel",
        fontName=_TABLE_FONT,
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#666666"),
        spaceAfter=0.3 * cm,
    ))

    story = []

    # ==========================
    # 1. Page de garde
    # ==========================
    story.append(Spacer(1, 3 * cm))
    story.append(HRFlowable(
        width="100%", thickness=3, color=colors.HexColor(MAIN_PURPLE_HEX), spaceAfter=0.6 * cm
    ))
    story.append(Paragraph("Rapport commenté", styles["CoverTitle"]))
    story.append(Paragraph("Risques Financiers", styles["CoverTitle"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(
        width="100%", thickness=1, color=colors.HexColor(MAIN_PURPLE_HEX), spaceAfter=0.6 * cm
    ))
    story.append(Paragraph(f"Période d'analyse : {periode_label}", styles["CoverSubtitle"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Document confidentiel", styles["CoverSubtitle"]))

    # ==========================
    # 2. Sections
    # ==========================
    story.append(PageBreak())
    for idx, sec in enumerate(sections):

        # --- Séparateur de section principale (## dans rapport.py) — sans PageBreak ---
        if sec.get("is_section_header"):
            story.append(Spacer(1, 0.6 * cm))
            story.append(HRFlowable(
                width="100%", thickness=3, color=colors.HexColor(MAIN_PURPLE_HEX), spaceAfter=0.3 * cm
            ))
            story.append(Paragraph(sec.get("title", ""), styles["SectionTitle"]))
            story.append(HRFlowable(
                width="100%", thickness=1, color=colors.HexColor(MAIN_PURPLE_HEX), spaceAfter=0.2 * cm
            ))
            continue

        title    = sec.get("title", "")
        subtitle = sec.get("subtitle", "")
        comment  = sec.get("comment", "")
        figures_png: Optional[List[bytes]] = sec.get("figures_png") or []

        # --- En-tête de section : main (X.) vs sous-section (X.Y) ---
        is_subsection = bool(re.match(r"^\d+\.\d+", title))
        if is_subsection:
            story.append(Paragraph(title, styles["SubSectionTitle"]))
            story.append(HRFlowable(
                width="100%", thickness=0.8,
                color=colors.HexColor("#c4a8d4"), spaceAfter=0.1 * cm
            ))
        else:
            story.append(Paragraph(title, styles["SectionTitle"]))
            story.append(HRFlowable(
                width="100%", thickness=2,
                color=colors.HexColor(MAIN_PURPLE_HEX), spaceAfter=0.1 * cm
            ))
        periode_txt = f"{subtitle} — {periode_label}" if subtitle else periode_label
        story.append(Paragraph(periode_txt, styles["PeriodLabel"]))

        # --- Bloc image(s) ou placeholder ---
        figures_png = [b for b in figures_png if b is not None]

        if len(figures_png) == 1:
            img = Image(io.BytesIO(figures_png[0]))
            img._restrictSize(17 * cm, 13 * cm)
            story.append(img)
            story.append(Spacer(1, 0.3 * cm))

        elif len(figures_png) >= 2:
            max_h = 8 * cm if len(figures_png) >= 3 else 11 * cm
            for b in figures_png:
                img = Image(io.BytesIO(b))
                img._restrictSize(17 * cm, max_h)
                story.append(img)
                story.append(Spacer(1, 0.2 * cm))

        else:
            # Aucun PNG fourni → placeholder
            story.append(_placeholder_box())
            story.append(Spacer(1, 0.3 * cm))

        # --- Tableau (si dispo) ---
        df_raw = sec.get("table")
        df_trunc = (
            _truncate_with_total(df_raw, max_rows=MAX_TABLE_ROWS)
            if isinstance(df_raw, pd.DataFrame) and not df_raw.empty
            else None
        )

        if df_trunc is not None and not df_trunc.empty:
            # Formatage texte (M€, %, bp, etc.) AVANT tout concat pour
            # conserver le dtype numérique → is_numeric_dtype() fonctionne
            df_fmt = _format_df_for_export(df_trunc)

            # Styles pour le wrapping dans les cellules
            from reportlab.lib.styles import ParagraphStyle as _PS
            _cell_style = _PS(
                "TblCell", fontName=_TABLE_FONT, fontSize=7, leading=9,
            )
            _hdr_style = _PS(
                "TblHdr", fontName=_TABLE_FONT_BOLD, fontSize=7, leading=9,
                textColor=colors.white,
            )

            # Largeurs proportionnelles : colonne texte plus large, numériques plus étroites
            TOTAL_W = 17 * cm
            def _col_w(name):
                n = str(name).lower()
                if any(x in n for x in ["(%)", "bp", "var", "duration"]):
                    return 1.8
                if "m€" in n or "delta" in n or "tendance" in n:
                    return 2.2
                return 4.0  # colonnes libellé / texte

            raw_w = [_col_w(c) for c in df_fmt.columns]
            col_widths = [w * TOTAL_W / sum(raw_w) for w in raw_w]

            # Styles Paragraph (la couleur est portée par le Paragraph, pas par TableStyle)
            from reportlab.lib.styles import ParagraphStyle as _PS
            _hdr_s  = _PS("TH", fontName=_TABLE_FONT_BOLD, fontSize=7, leading=9, textColor=colors.white)
            _cell_s = _PS("TD", fontName=_TABLE_FONT,      fontSize=7, leading=9, textColor=colors.black)
            _tot_s  = _PS("TT", fontName=_TABLE_FONT_BOLD, fontSize=7, leading=9, textColor=colors.white)

            def _trend_color(txt):
                t = txt.strip().upper()
                if "HAUSSE" in t: return TREND_UP_HEX
                if "BAISSE" in t: return TREND_DOWN_HEX
                if "STABLE" in t: return TREND_STABLE_HEX
                return None

            # Repère index colonne Tendance
            trend_col_idx = next(
                (j for j, c in enumerate(df_fmt.columns) if "TENDANCE" in str(c).upper()),
                None,
            )

            # Construction des cellules avec couleurs inline
            rows_data = df_fmt.astype(str).values.tolist()
            data = [[Paragraph(str(c), _hdr_s) for c in df_fmt.columns]]
            base_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(MAIN_PURPLE_HEX)),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]

            for row_idx, row in enumerate(rows_data, start=1):
                is_total = any(str(v).strip().upper() == "TOTAL" for v in row)
                style = _tot_s if is_total else _cell_s
                cells = []
                for col_idx, val in enumerate(row):
                    if not is_total and trend_col_idx is not None and col_idx == trend_col_idx:
                        hex_c = _trend_color(val)
                        if hex_c:
                            ps = _PS(f"Tend{row_idx}", fontName=_TABLE_FONT, fontSize=7,
                                     leading=9, textColor=colors.HexColor(hex_c))
                            cells.append(Paragraph(val, ps))
                            continue
                    cells.append(Paragraph(val, style))
                data.append(cells)
                if is_total:
                    base_style.append(
                        ("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor(MAIN_PURPLE_HEX))
                    )

            table = Table(data, colWidths=col_widths, hAlign="CENTER")
            table.setStyle(TableStyle(base_style))
            story.append(table)
            story.append(Spacer(1, 0.4 * cm))

        # --- Bloc "Commentaire" + champ éditable ---
        story.append(Paragraph("<b>Commentaire :</b>", styles["Normal"]))
        story.append(Spacer(1, 0.15 * cm))
        # Champ éditable dans le PDF : pré-rempli si commentaire saisi dans Streamlit,
        # sinon vide et modifiable directement dans le lecteur PDF.
        story.append(
            AnalyseTextField(
                field_name=f"analyse_{idx}",
                value=str(comment) if comment else "",
            )
        )
        story.append(PageBreak())

    # Build final PDF
    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
    buffer.seek(0)
    return buffer.getvalue()