"""CSV report generator."""

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List


class CsvReportGenerator:
    """Generator for CSV reports.

    Produces UTF-8 with BOM bytes so Excel opens them correctly.
    No float usage: monetary values are stored as integer centavos.
    """

    def _cents_label(self, cents: int) -> str:
        """Format integer centavos as BRL string without float."""
        amount = Decimal(cents) / Decimal(100)
        formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatted}"

    def generate_cash_flow_report(
        self,
        transactions: List[Dict[str, Any]],
        start_date: datetime,
        end_date: datetime,
    ) -> bytes:
        """Generate cash flow CSV.

        Args:
            transactions: List of transaction dicts (same shape as Excel generator).
            start_date: Report start date (unused in CSV body, kept for API symmetry).
            end_date: Report end date.

        Returns:
            UTF-8 bytes with BOM.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Data", "Tipo", "Cliente", "Descrição", "Entrada", "Saída", "Status"])
        for txn in transactions:
            dt = txn["date"]
            date_str = dt.strftime("%d/%m/%Y %H:%M") if isinstance(dt, datetime) else str(dt)
            inflow = self._cents_label(txn["amount"]) if txn["type"] in ("deposit", "yield") else ""
            outflow = self._cents_label(txn["amount"]) if txn["type"] == "withdrawal" else ""
            writer.writerow([
                date_str,
                txn["type"],
                txn["client_name"],
                txn["description"],
                inflow,
                outflow,
                txn["status"],
            ])
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def generate_clients_report(self, clients: List[Dict[str, Any]]) -> bytes:
        """Generate clients CSV.

        Args:
            clients: List of client dicts with centavos fields as integers.

        Returns:
            UTF-8 bytes with BOM.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Nome", "Email", "CPF", "Telefone", "Status",
            "Saldo (centavos)", "Total Investido (centavos)",
            "Rendimento Total (centavos)", "Fundo Garantidor (centavos)",
            "Criado em",
        ])
        for c in clients:
            writer.writerow([
                c["name"],
                c["email"],
                c.get("cpf", ""),
                c.get("phone", ""),
                c["status"],
                c.get("balance_cents", 0),
                c.get("total_invested_cents", 0),
                c.get("total_yield_cents", 0),
                c.get("fundo_garantidor_cents", 0),
                c["created_at"],
            ])
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def generate_transactions_report(self, transactions: List[Dict[str, Any]]) -> bytes:
        """Generate transactions CSV.

        Args:
            transactions: List of transaction dicts.

        Returns:
            UTF-8 bytes with BOM.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Cliente", "Data", "Confirmado em", "Tipo",
            "Status", "Valor (centavos)", "ID Pix", "Descrição",
        ])
        for t in transactions:
            writer.writerow([
                t["id"],
                t["client_name"],
                t["created_at"],
                t.get("confirmed_at", ""),
                t["transaction_type"],
                t["status"],
                t["amount_cents"],
                t.get("pix_transaction_id", ""),
                t.get("description", ""),
            ])
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def generate_yields_report(self, yields: List[Dict[str, Any]]) -> bytes:
        """Generate yields CSV.

        Args:
            yields: List of yield dicts derived from AuditLog details.

        Returns:
            UTF-8 bytes with BOM.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Usuário", "Série SGS", "Período De", "Período Até",
            "Taxa Efetiva", "Principal (centavos)", "Rendimento (centavos)",
            "Nº Parcela", "ID Assinatura", "ID Depósito Principal", "Data",
        ])
        for y in yields:
            writer.writerow([
                y["user_name"],
                y["sgs_series_id"],
                y["yield_period_from"],
                y["yield_period_to"],
                y["effective_rate"],
                y["principal_cents"],
                y["yield_cents"],
                y["installment_number"],
                y["subscription_id"],
                y["principal_deposit_id"],
                y["created_at"],
            ])
        return ("\ufeff" + output.getvalue()).encode("utf-8")
