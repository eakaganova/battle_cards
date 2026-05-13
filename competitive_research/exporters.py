from __future__ import annotations

import io
import json
from typing import Dict, List

import pandas as pd


def cells_to_dataframe(cells: Dict[str, Dict[str, object]]) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for competitor, fields in cells.items():
        row: Dict[str, object] = {"Конкурент": competitor}
        for field, cell in fields.items():
            data = cell.to_dict() if hasattr(cell, "to_dict") else cell
            row[field] = data.get("normalized_value") or data.get("extracted_value") or ""
            row[f"{field} · status"] = data.get("status", "")
            row[f"{field} · confidence"] = data.get("confidence_score", 0)
            row[f"{field} · source"] = data.get("source_url", "")
            row[f"{field} · fragment"] = data.get("source_fragment", "")
        rows.append(row)
    return pd.DataFrame(rows)


def export_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def export_excel(df: pd.DataFrame, insights: Dict[str, object], logs: List[Dict[str, str]], diff: List[Dict[str, object]]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Battle-card")
        pd.DataFrame(flatten_insights(insights)).to_excel(writer, index=False, sheet_name="Insights")
        pd.DataFrame(logs).to_excel(writer, index=False, sheet_name="Logs")
        pd.DataFrame(diff).to_excel(writer, index=False, sheet_name="Diff")
    return output.getvalue()


def export_markdown(df: pd.DataFrame, insights: Dict[str, object], diff: List[Dict[str, object]]) -> bytes:
    parts = ["# Competitive research", "", "## Battle-card", df.to_markdown(index=False), "", "## Insights"]
    for key, value in insights.items():
        parts.append(f"### {key}")
        parts.append(json.dumps(value, ensure_ascii=False, indent=2))
    if diff:
        parts.extend(["", "## Diff", pd.DataFrame(diff).to_markdown(index=False)])
    return "\n".join(parts).encode("utf-8")


def export_docx(df: pd.DataFrame, insights: Dict[str, object], diff: List[Dict[str, object]]) -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Competitive research", 0)
    document.add_heading("Battle-card", level=1)
    table = document.add_table(rows=1, cols=len(df.columns))
    for index, column in enumerate(df.columns):
        table.rows[0].cells[index].text = str(column)
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for index, column in enumerate(df.columns):
            cells[index].text = str(row[column])
    document.add_heading("Insights", level=1)
    for key, value in insights.items():
        document.add_heading(key, level=2)
        document.add_paragraph(json.dumps(value, ensure_ascii=False, indent=2))
    if diff:
        document.add_heading("Diff", level=1)
        document.add_paragraph(json.dumps(diff, ensure_ascii=False, indent=2))
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def export_pdf(df: pd.DataFrame, insights: Dict[str, object], diff: List[Dict[str, object]]) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return export_markdown(df, insights, diff)
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    y = height - 40
    for line in export_markdown(df.head(30), insights, diff).decode("utf-8").splitlines():
        if y < 40:
            pdf.showPage()
            y = height - 40
        pdf.drawString(35, y, line[:120])
        y -= 14
    pdf.save()
    return output.getvalue()


def google_sheets_payload(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)


def flatten_insights(insights: Dict[str, object]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key, value in insights.items():
        rows.append({"section": key, "content": json.dumps(value, ensure_ascii=False)})
    return rows
