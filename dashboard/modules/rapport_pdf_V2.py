# dashboard/modules/rapport_pdf_V2.py
"""
Rapport PDF — mêmes sections que l'original, avec logo + sommaire.

Corrections :
- section_header suit directement la première sous-section (pas de page vide)
- colonnes proportionnelles + Paragraph pour éviter les débordements de texte
- fallback kaleido à la volée si les bytes PNG pre-calculés sont None
"""

import io
from pathlib import Path
from typing import List, Dict, Optional

import pandas as pd
import plotly.io as pio

from reportlab.lib.enums import TA_CENTER, TA_LEFT
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
    HRFlowable,
    Flowable,
)

from modules.rapport_export import (
    _format_df_for_export,
    _truncate_with_total,
    _add_placeholder_capture,
    MAIN_PURPLE_HEX,
    TREND_UP_HEX,
    TREND_DOWN_HEX,
    TREND_STABLE_HEX,
)

# ── Palette ────────────────────────────────────────────────────────────────
_PURPLE     = colors.HexColor(MAIN_PURPLE_HEX)
_PURPLE_LT  = colors.HexColor("#e8d8f0")
_PURPLE_MID = colors.HexColor("#c4a8d4")
_GREY       = colors.HexColor("#555555")
_GREY_BG    = colors.HexColor("#f7f4fa")

_LOGO = Path(__file__).resolve().parent.parent.parent / "data" / "logo" / "logoeps.png"


# ── Styles ─────────────────────────────────────────────────────────────────
def _make_styles():
    s = getSampleStyleSheet()
    def add(name, **kw):
        if name not in s:
            s.add(ParagraphStyle(name=name, **kw))
    add("CenterTitle",  parent=s["Title"],    alignment=TA_CENTER)
    add("CenterH2",     parent=s["Heading2"], alignment=TA_CENTER)
    add("CenterNormal", parent=s["Normal"],   alignment=TA_CENTER)
    add("TocH",
        fontName="Helvetica-Bold", fontSize=10.5, leading=15,
        textColor=colors.HexColor("#4a2d5a"), spaceBefore=4, spaceAfter=2)
    add("TocS",
        fontName="Helvetica", fontSize=9.5, leading=14,
        textColor=_GREY, leftIndent=20, spaceAfter=1)
    add("SectionTitle",
        fontName="Helvetica-Bold", fontSize=12, leading=16,
        textColor=colors.HexColor("#4a2d5a"), spaceBefore=4, spaceAfter=2)
    add("SubTitle",
        fontName="Helvetica-Bold", fontSize=10, leading=14,
        textColor=_PURPLE, leftIndent=8, spaceBefore=4, spaceAfter=2)
    # Styles pour cellules de tableau
    add("TH",
        fontName="Helvetica-Bold", fontSize=7, leading=9,
        textColor=colors.white, alignment=TA_CENTER)
    add("TD",
        fontName="Helvetica", fontSize=7, leading=9,
        textColor=colors.HexColor("#1a1a2e"))
    add("TD_TOT",
        fontName="Helvetica-Bold", fontSize=7, leading=9,
        textColor=colors.white, alignment=TA_CENTER)
    return s


# ── Page de garde ──────────────────────────────────────────────────────────
def _cover_story(periode_label: str, styles) -> list:
    story = []

    if _LOGO.exists():
        logo_w = 7 * cm
        logo_h = logo_w * (105 / 480)
        img = Image(str(_LOGO), width=logo_w, height=logo_h)
        img.hAlign = "CENTER"
        story.append(Spacer(1, 1.5 * cm))
        story.append(img)
        story.append(Spacer(1, 0.6 * cm))
    else:
        story.append(Spacer(1, 2.5 * cm))

    story.append(HRFlowable(width="70%", thickness=2.5, color=_PURPLE,
                            spaceBefore=0, spaceAfter=0.4 * cm, hAlign="CENTER"))
    story.append(Paragraph("<b>Rapport commenté<br/>Risques financiers</b>",
                           styles["CenterTitle"]))
    story.append(Spacer(1, 0.4 * cm))

    # Encadré période
    pt = Table([[f"Période : {periode_label}"]], colWidths=[12 * cm], hAlign="CENTER")
    pt.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _PURPLE_LT),
        ("BOX",           (0, 0), (-1, -1), 1.0, _PURPLE),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 11),
        ("TEXTCOLOR",     (0, 0), (-1, -1), colors.HexColor("#4a2d5a")),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(pt)
    story.append(Spacer(1, 1.0 * cm))

    story.append(HRFlowable(width="70%", thickness=2.5, color=_PURPLE,
                            spaceBefore=0, spaceAfter=0.4 * cm, hAlign="CENTER"))
    story.append(Paragraph(
        "<font color='#714A80' size='9'>"
        "<i>Document confidentiel — usage interne strictement réservé</i>"
        "</font>",
        styles["CenterNormal"],
    ))
    story.append(PageBreak())
    return story


# ── Sommaire ───────────────────────────────────────────────────────────────
def _toc_story(sections: list, styles) -> list:
    import re
    story = []
    story.append(Paragraph("<b>Sommaire</b>", styles["CenterTitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=_PURPLE,
                            spaceBefore=0.1 * cm, spaceAfter=0.3 * cm))
    for sec in sections:
        if sec.get("is_section_header"):
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(sec.get("title", ""), styles["TocH"]))
        else:
            title = sec.get("title", "")
            is_sub = bool(re.match(r"^\d+\.\d+", title))
            if is_sub:
                story.append(Paragraph(f"    ◦  {title}", styles["TocS"]))
            else:
                story.append(Spacer(1, 0.1 * cm))
                story.append(Paragraph(f"  ●  {title}", styles["TocH"]))
    story.append(PageBreak())
    return story


# ── Largeurs de colonnes intelligentes ────────────────────────────────────
def _smart_col_widths(columns, total_w: float = 17 * cm) -> list:
    """Largeurs proportionnelles selon le type de colonne."""
    weights = []
    for col in columns:
        c = str(col).lower()
        if any(x in c for x in ["titre", "libellé", "libelle", "classe",
                                  "segment", "groupe", "emetteur", "secteur",
                                  "pays", "type", "duration"]):
            weights.append(3.8)
        elif "tendance" in c:
            weights.append(1.8)
        elif any(x in c for x in ["(%)", "alloc", "poids"]):
            weights.append(1.5)
        elif any(x in c for x in ["m€", "vm", "valeur"]):
            weights.append(2.0)
        elif "bp" in c or "spread" in c:
            weights.append(1.5)
        else:
            weights.append(2.0)
    total = sum(weights)
    return [w * total_w / total for w in weights]


# ── Grand espace graphique (à remplir manuellement) ───────────────────────
_GRAPH_H        = 8.0 * cm    # hauteur d'un graphique rendu
_GRAPH_H2       = 6.0 * cm    # hauteur quand 2 graphiques empilés
_PLACEHOLDER_H  = 10.5 * cm   # boîte vide (espace pour coller un screenshot)


def _graph_placeholder(story: list):
    """Boîte vide de secours — grand espace pour coller un screenshot."""
    tbl = Table(
        [[""]],
        colWidths=[17 * cm],
        rowHeights=[_PLACEHOLDER_H],
        hAlign="CENTER",
    )
    tbl.setStyle(TableStyle([
        ("BOX",        (0, 0), (-1, -1), 0.8, _PURPLE_MID),
        ("BACKGROUND", (0, 0), (-1, -1), _GREY_BG),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.3 * cm))


def _render_figures(sec: dict, story: list):
    """
    Rend les graphiques de la section dans le PDF.
    Priorité : bytes PNG pré-calculés (figures_png).
    Fallback  : rendu kaleido à la volée (figures_obj).
    Si aucun graphique disponible, affiche une boîte vide.
    """
    figs_png = [b for b in (sec.get("figures_png") or []) if b]
    figs_obj = sec.get("figures_obj") or []
    n = max(len(sec.get("figures_png") or []), len(figs_obj))
    img_h = _GRAPH_H if n <= 1 else _GRAPH_H2

    rendered = False
    raw_pngs = list(sec.get("figures_png") or [])

    for i in range(n):
        png = raw_pngs[i] if i < len(raw_pngs) else None
        obj = figs_obj[i] if i < len(figs_obj) else None

        if not png and obj is not None:
            try:
                obj.update_layout(paper_bgcolor="white", plot_bgcolor="white",
                                  font_color="#333333")
                png = pio.to_image(obj, format="png", width=1100, height=450, scale=1.5)
            except Exception as e:
                print(f"[rapport_pdf_V2] kaleido fig {i}: {e}")

        if png:
            img = Image(io.BytesIO(png), width=17 * cm, height=img_h)
            img.hAlign = "CENTER"
            story.append(img)
            story.append(Spacer(1, 0.15 * cm))
            rendered = True

    if not rendered:
        _graph_placeholder(story)
    else:
        story.append(Spacer(1, 0.15 * cm))


# ── Zone de commentaire éditable (AcroForm TextField) ─────────────────────
class _EditableComment(Flowable):
    """
    Champ texte PDF éditable.
    Le nom du champ est sanitisé en ASCII pour éviter les crashs ReportLab.
    """
    WIDTH  = 17 * cm
    HEIGHT = 3.0 * cm

    def __init__(self, field_name: str, value: str = ""):
        super().__init__()
        import re as _re
        # Nom ASCII uniquement, sans espaces ni caractères spéciaux
        self._name  = _re.sub(r"[^A-Za-z0-9_]", "_", field_name)[:60]
        # Valeur initiale : on remplace les caractères non-Latin-1 courants
        self._value = (
            str(value)
            .replace("€", "EUR").replace("→", "->").replace("–", "-")
            .replace("▲", "^").replace("▼", "v").replace("◆", "*")
        )
        self.width  = self.WIDTH
        self.height = self.HEIGHT

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()

        # Fond + bordure
        c.setFillColor(_GREY_BG)
        c.setStrokeColor(_PURPLE_MID)
        c.setLineWidth(0.8)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=1)

        # Champ texte AcroForm pré-rempli et éditable
        c.acroForm.textfield(
            name=self._name,
            value=self._value,
            tooltip="Cliquer pour saisir / modifier le commentaire",
            x=3, y=3,
            width=self.width - 6,
            height=self.height - 6,
            borderStyle="inset",
            borderWidth=0,
            fillColor=_GREY_BG,
            textColor=colors.black,
            fontSize=9,
            fieldFlags="multiline",
            relative=True,
            forceBorder=False,
        )
        c.restoreState()


# ── Rendu du tableau ───────────────────────────────────────────────────────
def _render_table(df_export: Optional[pd.DataFrame], story: list, styles):
    if df_export is None or df_export.empty:
        return

    col_widths = _smart_col_widths(df_export.columns)

    # En-tête avec Paragraph (retour à la ligne automatique)
    data = [[Paragraph(str(c), styles["TH"]) for c in df_export.columns]]

    # Colonne Tendance
    trend_col = next(
        (j for j, c in enumerate(df_export.columns) if "TENDANCE" in str(c).upper()), None
    )

    def _trend_style(txt):
        t = str(txt).upper()
        if "HAUSSE" in t:  return colors.HexColor(TREND_UP_HEX)
        if "BAISSE" in t:  return colors.HexColor(TREND_DOWN_HEX)
        if "STABLE" in t:  return colors.HexColor(TREND_STABLE_HEX)
        return None

    base_style = [
        ("BACKGROUND",    (0, 0), (-1, 0),  _PURPLE),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",          (0, 0), (-1, -1), 0.25, colors.grey),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, _GREY_BG]),
    ]

    for ri, row_vals in enumerate(df_export.astype(str).values.tolist(), start=1):
        is_total = any(v.strip().upper() == "TOTAL" for v in row_vals)
        sty = styles["TD_TOT"] if is_total else styles["TD"]
        cells = []
        for ci, val in enumerate(row_vals):
            sv = str(val)
            if not is_total and trend_col is not None and ci == trend_col:
                tc = _trend_style(sv)
                if tc:
                    ps = ParagraphStyle(f"Tr{ri}", fontName="Helvetica",
                                       fontSize=7, leading=9, textColor=tc)
                    cells.append(Paragraph(sv, ps))
                    continue
            cells.append(Paragraph(sv, sty))
        data.append(cells)
        if is_total:
            base_style += [
                ("BACKGROUND", (0, ri), (-1, ri), _PURPLE),
                ("TEXTCOLOR",  (0, ri), (-1, ri), colors.white),
            ]

    tbl = Table(data, colWidths=col_widths, hAlign="CENTER", repeatRows=1)
    tbl.setStyle(TableStyle(base_style))
    story.append(tbl)
    story.append(Spacer(1, 0.4 * cm))


# ══════════════════════════════════════════════════════════════════════════
#  BUILDER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════
def build_full_pdf_report_v2(
    sections: List[Dict],
    periode_label: str,
    logo_path: Optional[str] = None,
) -> bytes:
    import re
    styles = _make_styles()

    # Pré-traitement des tableaux
    prepared: List[Dict] = []
    for sec in sections:
        df = sec.get("table")
        df_export = None
        if df is not None and hasattr(df, "empty") and not df.empty:
            df_export = _format_df_for_export(_truncate_with_total(df, max_rows=12))
        prepared.append({**sec, "_df": df_export})

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )

    story: list = []
    story += _cover_story(periode_label, styles)
    story += _toc_story(sections, styles)

    first_content = True
    last_was_header = False  # évite la page vide après is_section_header

    for sec in prepared:

        # ── En-tête de chapitre ─────────────────────────────────────────
        if sec.get("is_section_header"):
            if not first_content:
                story.append(PageBreak())
            first_content = False
            last_was_header = True
            story.append(Paragraph(f"<b>{sec.get('title', '')}</b>",
                                   styles["SectionTitle"]))
            story.append(HRFlowable(width="100%", thickness=2, color=_PURPLE,
                                    spaceBefore=0, spaceAfter=0.25 * cm))
            continue

        # ── Section de contenu ──────────────────────────────────────────
        # Pas de PageBreak si on suit directement un en-tête de chapitre
        if not first_content and not last_was_header:
            story.append(PageBreak())
        first_content = False
        last_was_header = False

        title     = sec.get("title", "")
        subtitle  = sec.get("subtitle", "") or ""
        comment   = sec.get("comment", "") or ""
        df_export = sec.get("_df")

        is_sub = bool(re.match(r"^\d+\.\d+", title))
        if is_sub:
            story.append(Paragraph(f"<b>{title}</b>", styles["SubTitle"]))
            story.append(HRFlowable(width="100%", thickness=0.8, color=_PURPLE_MID,
                                    spaceBefore=0, spaceAfter=0.12 * cm))
        else:
            story.append(Paragraph(f"<b>{title}</b>", styles["CenterH2"]))
            story.append(HRFlowable(width="100%", thickness=1.5, color=_PURPLE,
                                    spaceBefore=0, spaceAfter=0.12 * cm))

        if subtitle:
            story.append(Paragraph(f"{subtitle} – {periode_label}",
                                   styles["CenterNormal"]))
            story.append(Spacer(1, 0.2 * cm))

        # Graphiques de la section (bytes PNG ou rendu kaleido en fallback)
        _render_figures(sec, story)

        # Tableau
        _render_table(df_export, story, styles)

        # Zone de commentaire — toujours éditable, pré-remplie si déjà saisi dans Streamlit
        story.append(Paragraph("<b>Commentaire :</b>", styles["TocH"]))
        story.append(Spacer(1, 0.1 * cm))
        sec_id = re.sub(r"[^A-Za-z0-9]", "_", sec.get("id", title))[:40]
        story.append(_EditableComment(f"comment_{sec_id}", value=comment))
        story.append(Spacer(1, 0.3 * cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
