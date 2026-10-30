"""In-memory printable history and administrative visit routing.

Uses the same ReportLab dependency as the existing chief-complaint slip. Existing
PDFs and their renderer are unchanged. The prepared case has fixed source dates;
printing never turns the current clock into a medical event date.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

INK = colors.HexColor("#213B35")
MUTED = colors.HexColor("#65736D")
TEAL = colors.HexColor("#176B5B")
LINE = colors.HexColor("#DAE4DE")
SOFT = colors.HexColor("#F1F6F3")


def _wrap(text, width, font="Helvetica", size=10):
    words = str(text or "Not provided").split()
    lines, line = [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if line and stringWidth(candidate, font, size) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + ([line] if line else [])


def _text(c, text, x, y, width, *, size=10, leading=14, bold=False, color=INK):
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFillColor(color)
    c.setFont(font, size)
    for line in _wrap(text, width, font, size):
        c.drawString(x, y, line)
        y -= leading
    return y


def _date(value):
    from datetime import date
    return date.fromisoformat(value).strftime("%d %b %Y")


def _header(c, width, height, title, patient, report_date, margin):
    c.setFillColor(TEAL)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(margin, height - margin, "optha")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawRightString(width - margin, height - margin + 2, "OPHTHALMOLOGY")
    c.setStrokeColor(LINE)
    c.line(margin, height - margin - 18, width - margin, height - margin - 18)
    y = height - margin - 46
    y = _text(c, title, margin, y, width - 2 * margin, size=19, leading=25, bold=True)
    y -= 3
    y = _text(c, f"{patient['name']}  |  {patient['age']} years  |  {patient['id']}",
              margin, y, width - 2 * margin, size=10, leading=14)
    y = _text(c, "History date: " + _date(report_date), margin, y - 3,
              width - 2 * margin, size=9, leading=13, color=MUTED)
    return y - 20


def _footer(c, width, margin, *, report=False):
    c.setStrokeColor(LINE)
    c.line(margin, 45, width - margin, 45)
    _text(c, "Prepared case | " + ("Patient-reported history; clinician review required."
          if report else "Administrative route; clinic confirmation pending."),
          margin, 32, width - 2 * margin, size=7.5, leading=10, color=MUTED)


def _route_cards(c, steps, x, y, width, *, vertical=False):
    gap = 10
    card_width = width if vertical else (width - gap * (len(steps) - 1)) / len(steps)
    height = 70 if vertical else 86
    start_y = y
    for index, step in enumerate(steps):
        xx = x if vertical else x + index * (card_width + gap)
        yy = start_y - index * (height + gap) if vertical else start_y
        c.setFillColor(SOFT)
        c.setStrokeColor(LINE)
        c.roundRect(xx, yy - height, card_width, height, 6, fill=1, stroke=1)
        _text(c, f"0{index + 1}", xx + 13, yy - 18, card_width - 26, size=9, color=TEAL)
        room = "Room " + step["room"] if step.get("room") else "Care team"
        line_y = _text(c, room, xx + 13, yy - 38, card_width - 26,
                       size=15 if vertical else 13, leading=16, bold=True)
        _text(c, step["label"], xx + 13, min(line_y - 2, yy - 57), card_width - 26,
              size=9, leading=12, color=MUTED)
    return start_y - (len(steps) * (height + gap) - gap if vertical else height)


def generate_report(report):
    stream = BytesIO()
    width, height = A4
    margin = 43
    inner = width - 2 * margin
    c = canvas.Canvas(stream, pagesize=A4, invariant=1)
    c.setTitle("Ophthalmology history - " + report["patient"]["name"])
    c.setAuthor("Optha")
    y = _header(c, width, height, "Patient history & visit route", report["patient"], report["date"], margin)
    fields = report["fields"]
    chief = next(field for field in fields if field["id"] == "chief_complaint")
    c.setFillColor(SOFT)
    c.roundRect(margin, y - 69, inner, 69, 7, fill=1, stroke=0)
    _text(c, "CHIEF COMPLAINT", margin + 16, y - 20, inner - 32, size=8, color=TEAL)
    _text(c, chief["value"], margin + 16, y - 44, inner - 32, size=16, bold=True, leading=20)
    y -= 96
    remaining = [field for field in fields if field["id"] != "chief_complaint"]
    column = (inner - 26) / 2
    for index in range(0, len(remaining), 2):
        lowest = y
        for offset, field in enumerate(remaining[index:index + 2]):
            xx = margin + offset * (column + 26)
            _text(c, field["label"].upper(), xx, y, column, size=8, color=MUTED)
            bottom = _text(c, field["value"], xx, y - 18, column, size=11, leading=15)
            lowest = min(lowest, bottom)
        y = lowest - 20
    _text(c, "FOR CLINICIAN REVIEW", margin, y, inner, size=8, color=TEAL)
    y -= 16
    for note in report.get("uncertainties", []):
        y = _text(c, note, margin, y, inner, size=9, leading=13, color=MUTED)
    y -= 20
    c.setStrokeColor(LINE)
    c.line(margin, y, width - margin, y)
    y -= 25
    y = _text(c, "Your visit route", margin, y, inner, size=15, leading=20, bold=True)
    y = _text(c, "Staff-configured rooms before clinician consultation", margin, y - 3,
              inner, size=9, leading=13, color=MUTED)
    y = _route_cards(c, report["routing"]["steps"], margin, y - 10, inner)
    _text(c, report["routing"]["note"], margin, y - 17, inner, size=8, leading=11, color=MUTED)
    _footer(c, width, margin, report=True)
    c.showPage()
    c.save()
    return stream.getvalue()


def generate_visit(report):
    stream = BytesIO()
    width, height = A5
    margin = 30
    inner = width - 2 * margin
    c = canvas.Canvas(stream, pagesize=A5, invariant=1)
    c.setTitle("Visit route - " + report["patient"]["name"])
    c.setAuthor("Optha")
    y = _header(c, width, height, "Your visit route", report["patient"], report["date"], margin)
    y = _route_cards(c, report["routing"]["steps"], margin, y + 2, inner, vertical=True)
    _text(c, report["routing"]["note"], margin, y - 20, inner, size=9, leading=13, color=MUTED)
    _footer(c, width, margin)
    c.showPage()
    c.save()
    return stream.getvalue()
