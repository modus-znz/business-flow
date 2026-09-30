#!/usr/bin/env python3
"""Regenerate the synthetic sample invoice bundled in invoices/.

The PDF is generated, not scanned, and every value in it is invented. It exists
so that `bizflow process invoices/sample-invoice.pdf` works from a cold clone and
so CI can exercise the real harvest path end to end rather than mocking it.

    python3 tools/make_sample_invoice.py

Requires reportlab. It is a build-time-only dependency and is deliberately NOT
in pyproject.toml: the tool itself never generates a PDF.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "invoices" / "sample-invoice.pdf"

# 8 rows. EAN-13: the 800..839 prefix is the GS1 range reserved for in-store
# test use, so these are not real trade items.
#
# (ean, description, qty = boxes ordered, mpl = pieces per box, true unit price)
#
# The true unit price carries 4 decimals and each line total is computed from it
# unrounded, but the *printed* unit price is rounded to cents. That is the
# ordinary wholesale situation `bizflow analyze` exists to make visible: adding
# up the printed unit prices does not reproduce the printed total, and the gap is
# per-line rounding rather than a missing row. Every figure here is invented.
ROWS = [
    ("8000000000017", "Sample caffe d'arrostimento 1kg", 12, 6, "0.8353"),
    ("8000000000024", "Pane carasau integrale 500g", 24, 12, "0.2013"),
    ("8000000000031", "Olive verdi denocciolate 580g", 6, 6, "1.1471"),
    ("8000000000048", "Pecorino romano stagionato", 4, 2, "9.2531"),
    ("8000000000055", "Pasta artigianale rigata 500g", 30, 10, "0.1453"),
    ("8000000000062", "Vino bianco frizzante 750ml", 12, 6, "0.9517"),
    ("8000000000079", "Acqua minerale naturale 1,5L", 40, 12, "0.0293"),
    ("8000000000086", "Conserva di pomodoro 700g", 8, 4, "0.9881"),
]

# x positions are the RIGHT edge of each column, in mm. A4 is 210mm wide, so
# 200mm is the last usable edge with a 10mm margin.
COL_QTY, COL_MPL, COL_PRICE, COL_UNIT, COL_TOTAL = 100, 125, 150, 175, 200

HEADER = [
    ("Q.tà", COL_QTY),
    ("Mpl", COL_MPL),
    ("Prezzo", COL_PRICE),
    ("P.zo Pz Imp.", COL_UNIT),
    ("P.zo Totale", COL_TOTAL),
]


def eur(x):
    """Italian money formatting: two decimals, comma decimal separator.

    The comma matters. extract.NUM only matches a comma-separated amount, so a
    sample PDF printed with dots would fail to harvest by design, not by bug.
    """
    return f"{x:.2f}".replace(".", ",")


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, h - 20 * mm, "Sample Vendor S.r.l.")
    c.drawString(20 * mm, h - 25 * mm, "Via Esempio 1 - 00100 Esempio (RM)")
    c.drawString(20 * mm, h - 29 * mm, "P. I.V.A.: IT00000000000")

    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 36 * mm, "N\u00b0 Documento: SAMPLE-0001        Data Emissione: 01/09/2026")

    c.setFont("Helvetica-Bold", 9)
    for label, x in HEADER:
        c.drawRightString(x * mm, h - 42 * mm, label)

    y = h - 49 * mm
    c.setFont("Helvetica", 8.5)
    declared = 0.0
    for ean, desc, qty, mpl, unit in ROWS:
        unit = float(unit)
        printed = round(unit, 2)
        total = qty * mpl * unit
        declared += round(total, 2)
        c.drawString(20 * mm, y, ean)
        c.drawString(45 * mm, y, desc)
        c.drawRightString(COL_QTY * mm, y, str(qty))
        c.drawRightString(COL_MPL * mm, y, str(mpl))
        c.drawRightString(COL_PRICE * mm, y, eur(printed))
        c.drawRightString(COL_UNIT * mm, y, eur(printed))
        c.drawRightString(COL_TOTAL * mm, y, eur(total))
        y -= 6 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(COL_TOTAL * mm, y, f"Totale Documento: {eur(declared)} EUR")

    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20 * mm, 12 * mm, "SYNTHETIC SAMPLE - every value invented, for testing only.")

    c.showPage()
    c.save()

    print(f"{OUT}  {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    build()
