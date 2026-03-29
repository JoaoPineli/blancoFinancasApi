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
        from weasyprint import HTML  # lazy import: avoids GLib warnings on startup
        buf = BytesIO()
        HTML(string=html).write_pdf(buf)
        buf.seek(0)
        return buf

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
