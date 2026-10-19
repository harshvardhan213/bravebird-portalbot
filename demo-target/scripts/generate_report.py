"""Render a small PDF report from workflow inputs.

Same inputs -> byte-identical PDF (no timestamps or random ids), so re-running
a job gives the same document.
"""
import argparse
import hashlib
from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


# No creation timestamp or random document ID: same inputs -> byte-identical PDF.
rl_config.invariant = 1


def line_items(report_type: str, month: str, customer: str) -> list[list[str]]:
    # Derive stable pseudo-random amounts from the inputs so each combination
    # yields a visibly different document.
    seed = hashlib.sha256(f"{report_type}|{month}|{customer}".encode()).digest()
    names = ["Platform fee", "Usage", "Support", "Storage", "Add-ons"]
    rows = [["Item", "Qty", "Amount (INR)"]]
    total = 0
    for i, name in enumerate(names):
        qty = seed[i] % 9 + 1
        amount = (seed[i + 8] * 37 + seed[i + 16]) % 9000 + 500
        total += amount
        rows.append([name, str(qty), f"{amount:,}"])
    rows.append(["Total", "", f"{total:,}"])
    return rows


def build(report_type: str, month: str, customer: str, variant: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(out), pagesize=A4, title=f"{report_type} {month}")
    table = Table(line_items(report_type, month, customer), colWidths=[220, 60, 120])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#24292f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    doc.build([
        Paragraph(f"Bravebird Demo — {report_type.title()}", styles["Title"]),
        Paragraph(f"Customer: {customer}", styles["Normal"]),
        Paragraph(f"Period: {month}", styles["Normal"]),
        Paragraph(f"Template: {variant}", styles["Normal"]),
        Spacer(1, 16),
        table,
    ])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--report-type", required=True)
    p.add_argument("--month", required=True)
    p.add_argument("--customer", required=True)
    p.add_argument("--variant", default="main")
    p.add_argument("--out", default="out/report.pdf")
    a = p.parse_args()
    build(a.report_type, a.month, a.customer, a.variant, Path(a.out))
    print(f"wrote {a.out}")
