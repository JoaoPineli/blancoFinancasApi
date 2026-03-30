"""PDF report generator for admin reports using WeasyPrint."""

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, Dict, List


class PdfReportGenerator:
    """Generator for PDF admin reports.

    Uses WeasyPrint (lazy import to avoid GLib warnings on startup).
    No float usage for monetary values.
    """

    def _to_brl(self, amount: Decimal) -> str:
        """Format Decimal as BRL string without float."""
        formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatted}"

    def generate_cash_flow_report(
        self,
        transactions: List[Dict[str, Any]],
        start_date: datetime,
        end_date: datetime,
    ) -> BytesIO:
        """Generate cash flow PDF.

        Args:
            transactions: List of transaction dicts (same shape as Excel generator).
            start_date: Report start date.
            end_date: Report end date.

        Returns:
            BytesIO buffer with PDF bytes.
        """
        html = self._render_cash_flow_html(transactions, start_date, end_date)
        try:
            from weasyprint import HTML  # lazy import: avoids GLib warnings on startup

            buf = BytesIO()
            HTML(string=html).write_pdf(buf)
            buf.seek(0)
            return buf
        except (ImportError, OSError):
            # WeasyPrint depends on native libraries (GLib/Cairo/Pango) that may not
            # be available in some environments (e.g. Windows CI/test machines).
            return self._generate_basic_cash_flow_pdf(transactions, start_date, end_date)

    def _generate_basic_cash_flow_pdf(
        self,
        transactions: List[Dict[str, Any]],
        start_date: datetime,
        end_date: datetime,
    ) -> BytesIO:
        """Generate a simple one-page PDF without external native dependencies."""
        total_inflow = Decimal("0")
        total_outflow = Decimal("0")

        lines = [
            "BLANCO FINANCAS - Relatorio de Fluxo de Caixa",
            f"Periodo: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}",
            "",
            "Data | Tipo | Cliente | Valor | Status | Descricao",
        ]

        for txn in transactions:
            dt = txn["date"]
            date_str = dt.strftime("%d/%m/%Y %H:%M") if isinstance(dt, datetime) else str(dt)
            amount = Decimal(txn["amount"]) / Decimal(100)
            signed_amount = Decimal("0")
            if txn["type"] in ("deposit", "yield"):
                total_inflow += amount
                signed_amount = amount
            elif txn["type"] == "withdrawal":
                total_outflow += amount
                signed_amount = amount * Decimal("-1")

            description = str(txn.get("description") or "").replace("\n", " ").strip()
            line = (
                f"{date_str} | {txn['type']} | {txn['client_name']} | "
                f"{self._to_brl(signed_amount)} | {txn['status']} | {description}"
            )
            lines.append(line[:120])

        lines.extend(
            [
                "",
                f"Total entradas: {self._to_brl(total_inflow)}",
                f"Total saidas: {self._to_brl(total_outflow)}",
                f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            ]
        )

        return self._build_simple_pdf(lines)

    def _build_simple_pdf(self, lines: List[str]) -> BytesIO:
        """Build a valid, minimal PDF document with plain text lines."""
        safe_lines = [self._escape_pdf_text(line) for line in lines[:45]]

        text_commands = ["BT", "/F1 10 Tf", "50 800 Td"]
        first_line = safe_lines[0] if safe_lines else "Relatorio"
        text_commands.append(f"({first_line}) Tj")

        for line in safe_lines[1:]:
            text_commands.append("0 -14 Td")
            text_commands.append(f"({line}) Tj")

        text_commands.append("ET")
        content_stream = "\n".join(text_commands).encode("latin-1", "replace")

        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            (
                f"<< /Length {len(content_stream)} >>\nstream\n".encode("ascii")
                + content_stream
                + b"\nendstream"
            ),
        ]

        buffer = BytesIO()
        buffer.write(b"%PDF-1.4\n")
        offsets = [0]

        for obj_number, obj_content in enumerate(objects, start=1):
            offsets.append(buffer.tell())
            buffer.write(f"{obj_number} 0 obj\n".encode("ascii"))
            buffer.write(obj_content)
            buffer.write(b"\nendobj\n")

        xref_position = buffer.tell()
        buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        buffer.write(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            buffer.write(f"{offset:010} 00000 n \n".encode("ascii"))

        buffer.write(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_position}\n%%EOF"
            ).encode("ascii")
        )
        buffer.seek(0)
        return buffer

    def _escape_pdf_text(self, text: str) -> str:
        """Escape text so it can be safely used in a PDF literal string."""
        return (
            text.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("\r", " ")
            .replace("\n", " ")
        )

    def _render_cash_flow_html(
        self,
        transactions: List[Dict[str, Any]],
        start_date: datetime,
        end_date: datetime,
    ) -> str:
        rows_html = ""
        total_inflow = Decimal("0")
        total_outflow = Decimal("0")

        for txn in transactions:
            dt = txn["date"]
            date_str = dt.strftime("%d/%m/%Y %H:%M") if isinstance(dt, datetime) else str(dt)
            amount = Decimal(txn["amount"]) / Decimal(100)
            inflow_str = ""
            outflow_str = ""
            if txn["type"] in ("deposit", "yield"):
                inflow_str = self._to_brl(amount)
                total_inflow += amount
            elif txn["type"] == "withdrawal":
                outflow_str = self._to_brl(amount)
                total_outflow += amount

            # Escape HTML special characters in description
            desc = (
                txn["description"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            rows_html += (
                f"<tr>"
                f"<td>{date_str}</td>"
                f"<td>{txn['type']}</td>"
                f"<td>{txn['client_name']}</td>"
                f"<td>{desc}</td>"
                f"<td class='money'>{inflow_str}</td>"
                f"<td class='money'>{outflow_str}</td>"
                f"<td>{txn['status']}</td>"
                f"</tr>\n"
            )

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Fluxo de Caixa - Blanco Finanças</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 30px; font-size: 11px; }}
  h1 {{ color: #1a365d; text-align: center; font-size: 18px; margin-bottom: 4px; }}
  h2 {{ text-align: center; font-size: 14px; color: #2d3748; margin-top: 0; }}
  .period {{ text-align: center; color: #4a5568; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background-color: #1a365d; color: white; padding: 7px 6px; text-align: left; font-size: 10px; }}
  td {{ padding: 5px 6px; border-bottom: 1px solid #e2e8f0; font-size: 10px; }}
  .money {{ text-align: right; white-space: nowrap; }}
  tr.totals td {{ font-weight: bold; border-top: 2px solid #1a365d; background-color: #f7fafc; }}
  .footer {{ margin-top: 20px; text-align: center; color: #718096; font-size: 9px; }}
</style>
</head>
<body>
<h1>BLANCO FINANÇAS</h1>
<h2>Relatório de Fluxo de Caixa</h2>
<p class="period">Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}</p>
<table>
<thead>
<tr>
  <th>Data</th><th>Tipo</th><th>Cliente</th><th>Descrição</th>
  <th>Entrada</th><th>Saída</th><th>Status</th>
</tr>
</thead>
<tbody>
{rows_html}
<tr class="totals">
  <td colspan="4">TOTAIS</td>
  <td class="money">{self._to_brl(total_inflow)}</td>
  <td class="money">{self._to_brl(total_outflow)}</td>
  <td></td>
</tr>
</tbody>
</table>
<div class="footer">Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
</body>
</html>"""
