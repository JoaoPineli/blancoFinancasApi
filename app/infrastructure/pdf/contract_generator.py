"""Contract PDF generator using WeasyPrint."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import UUID

from app.domain.entities.user import User
from app.domain.entities.plan import Plan


class ContractPdfGenerator:
    """PDF generator for contract documents.

    Generates immutable PDF contracts based on User and Plan data.
    """

    def __init__(self, storage_path: str = "storage/contracts") -> None:
        """Initialize PDF generator.

        Args:
            storage_path: Base path for storing generated PDFs
        """
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        user: User,
        plan: Plan,
        contract_id: UUID,
    ) -> str:
        """Generate contract PDF.

        Args:
            user: User entity
            plan: Plan entity
            contract_id: Contract UUID

        Returns:
            Path to generated PDF file
        """
        # Generate HTML content
        html_content = self._render_html(user, plan, contract_id)

        # Generate PDF
        filename = f"contract_{contract_id}.pdf"
        filepath = self._storage_path / filename

        # Lazy import: WeasyPrint pulls in native GTK/GLib deps on Windows.
        # Importing at runtime avoids noisy GLib warnings during Uvicorn reloads.
        from weasyprint import HTML

        HTML(string=html_content).write_pdf(str(filepath))

        return str(filepath)

    def _render_html(
        self,
        user: User,
        plan: Plan,
        contract_id: UUID,
    ) -> str:
        """Render contract HTML template."""
        max_duration = (
            f"até {plan.max_duration_months} meses"
            if plan.max_duration_months is not None
            else "indeterminado"
        )

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Contrato de Investimento - Blanco Finanças</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            line-height: 1.6;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .header h1 {{
            color: #1a365d;
            margin-bottom: 5px;
        }}
        .section {{
            margin-bottom: 20px;
        }}
        .section h2 {{
            color: #2d3748;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 5px;
        }}
        .info-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        .info-table td {{
            padding: 8px;
            border: 1px solid #e2e8f0;
        }}
        .info-table td:first-child {{
            font-weight: bold;
            width: 200px;
            background-color: #f7fafc;
        }}
        .signature {{
            margin-top: 50px;
            display: flex;
            justify-content: space-between;
        }}
        .signature-box {{
            width: 45%;
            text-align: center;
        }}
        .signature-line {{
            border-top: 1px solid #2d3748;
            margin-top: 60px;
            padding-top: 10px;
        }}
        .footer {{
            margin-top: 40px;
            text-align: center;
            font-size: 12px;
            color: #718096;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>BLANCO FINANÇAS</h1>
        <h2>Contrato de Investimento</h2>
        <p>Contrato Nº: {contract_id}</p>
    </div>

    <div class="section">
        <h2>1. DADOS DO CONTRATANTE</h2>
        <table class="info-table">
            <tr>
                <td>Nome Completo</td>
                <td>{user.name}</td>
            </tr>
            <tr>
                <td>CPF</td>
                <td>{user.cpf.formatted}</td>
            </tr>
            <tr>
                <td>E-mail</td>
                <td>{user.email.value}</td>
            </tr>
            <tr>
                <td>Telefone</td>
                <td>{user.phone or 'Não informado'}</td>
            </tr>
        </table>
    </div>

    <div class="section">
        <h2>2. DADOS DO PLANO</h2>
        <table class="info-table">
            <tr>
                <td>Plano</td>
                <td>{plan.title}</td>
            </tr>
            <tr>
                <td>Duração mínima</td>
                <td>{plan.min_duration_months} meses</td>
            </tr>
            <tr>
                <td>Duração máxima</td>
                <td>{max_duration}</td>
            </tr>
            <tr>
                <td>Fundo de proteção</td>
                <td>{plan.guarantee_fund_percent_1}%</td>
            </tr>
        </table>
    </div>

    <div class="section">
        <h2>3. TERMOS E CONDIÇÕES</h2>
        <p>{plan.description}</p>
        <p>O CONTRATANTE declara ter lido e concordado com todos os termos e condições
        estabelecidos neste contrato, incluindo as regras de rendimento baseadas na
        poupança e a retenção do Fundo de proteção.</p>
    </div>

    <div class="signature">
        <div class="signature-box">
            <div class="signature-line">
                <p>{user.name}</p>
                <p>CONTRATANTE</p>
            </div>
        </div>
        <div class="signature-box">
            <div class="signature-line">
                <p>Blanco Finanças</p>
                <p>CONTRATADA</p>
            </div>
        </div>
    </div>

    <div class="footer">
        <p>Data de Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        <p>Este documento é válido como instrumento particular de contrato.</p>
    </div>
</body>
</html>
        """
        return html
