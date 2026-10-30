# A5 chief-complaint slip for the doctor. English values only (ReportLab does
# not shape Devanagari), so values are printed in Helvetica.

import os
import re
from datetime import datetime

from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PDF_DIR = "pdfs"
GREY = colors.Color(0.45, 0.45, 0.45)


def _fmt(v):
    if v is None or str(v).strip() == "":
        return "-"
    return str(v)


def _wrap(text, font, size, max_width):
    # Greedy word wrap to max_width; returns a list of lines.
    words = text.split()
    if not words:
        return ["-"]
    lines, line = [], words[0]
    for w in words[1:]:
        trial = line + " " + w
        if stringWidth(trial, font, size) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines


def _pdf_path(session):
    phone = re.sub(r"\D", "", session.get("phone") or "")[-10:] or session["session_id"]
    existing = [f for f in os.listdir(PDF_DIR) if f.endswith(".pdf")]
    # Global running number: unique and ever-increasing, so slips sort in the
    # order patients call. Taken from the highest number already on disk + 1.
    seq = 1
    for f in existing:
        m = re.match(r"(\d+)_", f)
        if m:
            seq = max(seq, int(m.group(1)) + 1)
    # How many times this phone has been seen before (the "(n)" suffix), counting
    # both the new "<seq>_<phone>(n)" and any legacy "<phone>(n)" files.
    count = sum(1 for f in existing
                if re.search(rf"(?:^|_){re.escape(phone)}\(", f)) + 1
    return os.path.join(PDF_DIR, f"{seq:04d}_{phone}({count}).pdf")


def generate(session, output_path=None, *, clinic_name=None):
    os.makedirs(PDF_DIR, exist_ok=True)
    path = output_path or _pdf_path(session)
    w, h = A5
    m = 20 * mm
    inner = w - 2 * m
    c = canvas.Canvas(path, pagesize=A5)
    y = h - m

    def hr(yy):
        c.setStrokeColor(GREY)
        c.setLineWidth(0.5)
        c.line(m, yy, w - m, yy)

    def footer():
        is_partial = session.get("status") == "partial"
        c.setFillColor(colors.Color(0.75, 0.1, 0.1) if is_partial else GREY)
        c.setFont("Helvetica-Bold" if is_partial else "Helvetica", 7)
        phone_disp = re.sub(r"\D", "", session.get("phone") or "")[-10:] or "-"
        partial_tag = " | PARTIAL RECORD — call dropped" if is_partial else ""
        c.drawString(m, 12 * mm,
                     f"AI-generated | Review required | {session['session_id']} | {phone_disp}{partial_tag}")

    def ensure_space(height):
        nonlocal y
        if y - height >= 22 * mm:
            return False
        footer()
        c.showPage()
        y = h - m
        c.setFillColor(GREY)
        c.setFont("Helvetica", 8)
        c.drawString(m, y, "CHIEF COMPLAINT RECORD — continued")
        y -= 8 * mm
        return True

    def block(label, value, value_font, value_size, line_gap):
        nonlocal y
        ensure_space(4.5 * mm + line_gap)
        c.setFillColor(GREY)
        c.setFont("Helvetica", 7)
        c.drawString(m, y, label)
        y -= 4.5 * mm
        c.setFillColor(colors.black)
        c.setFont(value_font, value_size)
        for ln in _wrap(_fmt(value), value_font, value_size, inner):
            if ensure_space(line_gap):
                c.setFillColor(GREY)
                c.setFont("Helvetica", 7)
                c.drawString(m, y, label + " (continued)")
                y -= 4.5 * mm
            c.setFillColor(colors.black)
            c.setFont(value_font, value_size)
            c.drawString(m, y, ln)
            y -= line_gap
        y -= 2 * mm

    # Header
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w / 2, y, clinic_name or os.environ.get("CLINIC_NAME", "Clinic"))
    y -= 6 * mm
    c.setFillColor(GREY)
    c.setFont("Helvetica", 8)
    c.drawCentredString(w / 2, y, " ".join("CHIEF COMPLAINT RECORD"))
    y -= 5 * mm
    hr(y)
    y -= 6 * mm

    # Patient row
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    row = (f"{_fmt(session.get('name'))}    |    Age {_fmt(session.get('age'))}"
           f"    |    UHID {_fmt(session.get('uhid'))}")
    c.drawString(m, y, row)
    y -= 4.5 * mm
    c.setFillColor(GREY)
    c.setFont("Helvetica", 8)
    c.drawString(m, y, datetime.now().strftime("%d-%m-%Y  %H:%M"))
    y -= 5 * mm
    hr(y)
    y -= 8 * mm

    # Chief complaint (most prominent)
    block("CHIEF COMPLAINT", session.get("chief_complaint"),
          "Helvetica-Bold", 13, 6 * mm)
    y -= 1 * mm

    for label, key in [
        ("EYE", "laterality"),
        ("DURATION", "duration"),
        ("FOLLOW-UP FINDING", "dynamic_follow_up"),
        ("PRIOR TREATMENT", "prior_treatment"),
        ("COMORBIDITIES", "comorbidities"),
        ("MEDICATIONS", "medications"),
    ]:
        block(label, session.get(key), "Helvetica", 11, 5 * mm)

    for label, key in [("OTHER PATIENT-REPORTED DETAILS", "additional_details"),
                       ("NEEDS CLARIFICATION", "uncertainties")]:
        if session.get(key) and session[key] != "-":
            block(label, session[key], "Helvetica", 11, 5 * mm)

    # Signature + footer
    ensure_space(17 * mm)
    y -= 3 * mm
    hr(y)
    y -= 10 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(m, y, "Doctor's signature & stamp: ____________________")

    footer()

    c.showPage()
    c.save()
    print(f"PDF saved: {path}")
    return path
