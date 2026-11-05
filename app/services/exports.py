"""خروجی گزارش‌ها: CSV، Excel (اعداد واقعی) و PDF فارسی راست‌چین."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from ..config import BASE_DIR
from .calendar_utils import fmt_date

FONT_DIR = BASE_DIR / "app" / "static" / "vendor" / "fonts"
NUMERIC = {"money", "number", "units", "percent"}
PLACES = {"money": Decimal("0.01"), "number": Decimal("0.0001"), "units": Decimal("0.000001"), "percent": Decimal("0.0001")}


def _num(v, type_):
    if v is None or v == "":
        return None
    d = v if isinstance(v, Decimal) else Decimal(str(v))
    return d.quantize(PLACES[type_], rounding=ROUND_HALF_UP)


def cell_value(v, type_, calendar):
    """مقدار قابل‌ذخیره: عدد برای انواع عددی، متن برای بقیه."""
    if type_ in NUMERIC:
        n = _num(v, type_)
        return None if n is None else n
    if type_ == "date":
        return fmt_date(v, calendar) if v else ""
    return "" if v is None else str(v)


def display(v, type_, calendar):
    """نمایش با جداکننده هزارگان (برای PDF)."""
    cv = cell_value(v, type_, calendar)
    if cv is None or cv == "":
        return "—" if type_ in NUMERIC else ""
    if type_ in NUMERIC:
        s = f"{cv:,.2f}" if type_ == "money" else (f"{cv:,.2f}" if type_ == "percent" else f"{cv.normalize():,f}")
        if type_ == "percent":
            s += "%"
        elif type_ == "money":
            s = s[:-3] if s.endswith(".00") else s
        return s
    return str(cv)


def _unit_label(settings_label: str) -> str:
    return settings_label or "تومان"


def _summary_rows(report, calendar):
    out = []
    for s in report.get("summary", []):
        out.append((s["label"], cell_value(s["value"], s["type"], calendar) if s["value"] is not None else (s.get("note") or "—"), s["type"]))
    return out


# ------------------------------------------------------------------ CSV
def to_csv(report: dict, calendar: str, unit: str = "تومان") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([report["title"]])
    if report.get("subtitle"):
        w.writerow([report["subtitle"]])
    w.writerow([f"واحد پول: {unit}"])
    for label, val, _ in _summary_rows(report, calendar):
        w.writerow([label, "" if val is None else (format(val, "f") if isinstance(val, Decimal) else val)])
    w.writerow([])
    cols = report["columns"]
    w.writerow([c["label"] for c in cols])
    for r in report["rows"]:
        row = []
        for c in cols:
            v = cell_value(r.get(c["key"]), c["type"], calendar)
            row.append("" if v is None else (format(v, "f") if isinstance(v, Decimal) else v))
        w.writerow(row)
    for n in report.get("notes", []):
        w.writerow([n])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")  # BOM برای نمایش درست فارسی در Excel


# ----------------------------------------------------------------- XLSX
def to_xlsx(report: dict, calendar: str, unit: str = "تومان") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "گزارش"[:31]
    ws.sheet_view.rightToLeft = True
    head_fill = PatternFill("solid", fgColor="14243F")
    head_font = Font(bold=True, color="FFFFFF", name="Vazirmatn")
    base_font = Font(name="Vazirmatn")
    thin = Side(style="thin", color="D0D7E2")
    r = 1
    ws.cell(r, 1, report["title"]).font = Font(bold=True, size=14, name="Vazirmatn")
    r += 1
    if report.get("subtitle"):
        ws.cell(r, 1, report["subtitle"]).font = base_font
        r += 1
    ws.cell(r, 1, f"واحد پول: {unit}").font = base_font
    r += 2
    for label, val, typ in _summary_rows(report, calendar):
        ws.cell(r, 1, label).font = Font(bold=True, name="Vazirmatn")
        c = ws.cell(r, 2, float(val) if isinstance(val, Decimal) else val)
        c.font = base_font
        if isinstance(val, Decimal):
            c.number_format = _fmt(typ)
        r += 1
    r += 1
    cols = report["columns"]
    for j, c in enumerate(cols, 1):
        cell = ws.cell(r, j, c["label"])
        cell.fill, cell.font = head_fill, head_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    header_row = r
    for row in report["rows"]:
        r += 1
        for j, c in enumerate(cols, 1):
            v = cell_value(row.get(c["key"]), c["type"], calendar)
            if isinstance(v, Decimal):
                cell = ws.cell(r, j, float(v))  # عدد واقعی، نه متن
                cell.number_format = _fmt(c["type"])
            else:
                cell = ws.cell(r, j, v if v != "" else None)
            cell.font = base_font
            cell.border = Border(bottom=thin)
    r += 2
    for n in report.get("notes", []):
        ws.cell(r, 1, n).font = Font(italic=True, name="Vazirmatn", color="666666")
        r += 1
    for j, c in enumerate(cols, 1):
        width = max([len(str(c["label"]))] + [len(str(row.get(c["key"]) or "")) for row in report["rows"][:200]]) + 4
        ws.column_dimensions[get_column_letter(j)].width = min(max(width, 14), 34)
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 38)
    if report["rows"]:
        ws.freeze_panes = ws.cell(header_row + 1, 1)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _fmt(type_):
    return {"money": "#,##0", "units": "#,##0.######", "number": "#,##0.00", "percent": '0.00"%"'}[type_]


# ------------------------------------------------------------------ PDF
@lru_cache
def _setup_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont("Vazirmatn", str(FONT_DIR / "Vazirmatn-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Vazirmatn-Bold", str(FONT_DIR / "Vazirmatn-Bold.ttf")))
    return True


def _shape(text: str) -> str:
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(text))


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(_shape(trial), font, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def to_pdf(report: dict, calendar: str, unit: str = "تومان") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph
    from reportlab.lib.styles import ParagraphStyle

    _setup_fonts()
    cols = report["columns"]
    page = landscape(A4) if len(cols) > 5 else A4
    margin = 12 * mm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=report["title"], author="CapitalPilot")
    avail = page[0] - 2 * margin
    story = []
    title_style = ParagraphStyle("t", fontName="Vazirmatn-Bold", fontSize=15, alignment=2, leading=24, textColor=colors.HexColor("#0b1730"))
    sub_style = ParagraphStyle("s", fontName="Vazirmatn", fontSize=9.5, alignment=2, leading=16, textColor=colors.HexColor("#4a5875"))
    story.append(Paragraph(_shape(report["title"]), title_style))
    sub = " — ".join(x for x in (report.get("subtitle"), f"واحد پول: {unit}") if x)
    story.append(Paragraph(_shape(sub), sub_style))
    story.append(Spacer(1, 6))

    def tbl(data, widths, header=True, align_right_cols=()):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        st = [("FONTNAME", (0, 0), (-1, -1), "Vazirmatn"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
              ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9d2e3")),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14243f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                   ("FONTNAME", (0, 0), (-1, 0), "Vazirmatn-Bold"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fb")])]
        t.setStyle(TableStyle(st))
        return t

    # خلاصه
    srows = _summary_rows(report, calendar)
    if srows:
        w_label, w_val = avail * 0.55, avail * 0.45
        data = []
        for label, val, typ in srows:
            if isinstance(val, Decimal):
                vtxt = display(val, typ, calendar)
            else:
                vtxt = "" if val is None else str(val)
            lines = _wrap(vtxt, "Vazirmatn", 8.5, w_val - 10) if typ == "text" or not isinstance(val, Decimal) else [vtxt]
            vcell = "\n".join(_shape(l) if not isinstance(val, Decimal) else l for l in lines)
            data.append([vcell, "\n".join(_shape(l) for l in _wrap(label, "Vazirmatn", 8.5, w_label - 10))])
        story.append(tbl(data, [w_val, w_label], header=False))
        story.append(Spacer(1, 8))
    # جدول اصلی (ستون اول سمت راست)
    if report["rows"]:
        ordered = list(reversed(cols))
        weights = [1.6 if c["type"] == "text" else 1.0 for c in ordered]
        widths = [avail * w / sum(weights) for w in weights]
        head = ["\n".join(_shape(l) for l in _wrap(c["label"], "Vazirmatn-Bold", 8.5, wd - 8)) for c, wd in zip(ordered, widths)]
        data = [head]
        for r in report["rows"]:
            row = []
            for c, wd in zip(ordered, widths):
                txt = display(r.get(c["key"]), c["type"], calendar)
                row.append("\n".join(_shape(l) for l in _wrap(txt, "Vazirmatn", 8.5, wd - 8)) if c["type"] == "text" else txt)
            data.append(row)
        story.append(tbl(data, widths))
    else:
        story.append(Paragraph(_shape("داده‌ای برای نمایش وجود ندارد."), sub_style))
    story.append(Spacer(1, 8))
    for n in report.get("notes", []):
        for line in _wrap("• " + n, "Vazirmatn", 8.5, avail - 10):
            story.append(Paragraph(_shape(line), sub_style))
    foot = f"CapitalPilot — {fmt_date(datetime.now(), calendar)}"

    def _footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Vazirmatn", 7.5)
        canvas.setFillColor(colors.HexColor("#6b7894"))
        canvas.drawString(margin, 8 * mm, foot)
        canvas.drawRightString(page[0] - margin, 8 * mm, _shape(f"صفحه {d.page}"))
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


EXPORTERS = {
    "csv": (to_csv, "text/csv; charset=utf-8", "csv"),
    "xlsx": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": (to_pdf, "application/pdf", "pdf"),
}
