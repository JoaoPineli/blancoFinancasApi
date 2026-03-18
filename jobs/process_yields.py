"""Standalone job: process poupança yields for all principal deposits.

Executa o cálculo e crédito de rendimento da poupança para todos os aportes
registrados em principal_deposits.

Uso:
    python jobs/process_yields.py [--date YYYY-MM-DD]

    --date   Data de referência para cálculo (padrão: hoje em UTC).
             Use para reprocessar uma data específica (idempotente).

Retorno:
    Exit code 0  → sucesso
    Exit code 1  → erro (detalhes no log)

Cron (Task Scheduler):
    Executar diariamente às 00:05 BRT apontando para este script.
    Ver jobs/schedule_yields.bat para configuração automática.
"""

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timezone

# Adiciona raiz do projeto ao path para importar app.*
import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE_DIR)

from app.application.services.yield_service import YieldService
from app.infrastructure.bcb.exceptions import BCBUnavailableError
from app.infrastructure.db.session import async_session_factory


# ---------------------------------------------------------------------------
# Logging: console + arquivo de log rotativo diário
# ---------------------------------------------------------------------------

_LOG_DIR = os.path.join(_BASE_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_log_file = os.path.join(_LOG_DIR, "process_yields.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)
log = logging.getLogger("process_yields")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run(calculation_date: date) -> int:
    """Execute yield processing. Returns exit code (0 = ok, 1 = error)."""
    log.info("=== Início do job process_yields | data referência: %s ===", calculation_date)

    async with async_session_factory() as session:
        service = YieldService(session)
        try:
            result = await service.process_all_yields(calculation_date=calculation_date)
        except BCBUnavailableError as exc:
            log.error("BCB API indisponível: %s", exc.message)
            log.error("Job abortado. Nenhum rendimento foi creditado.")
            return 1
        except Exception as exc:
            log.exception("Erro inesperado durante o processamento: %s", exc)
            return 1

    log.info(
        "Concluído | aportes avaliados: %d | creditados: %d | total creditado: R$ %.2f",
        result.deposits_evaluated,
        result.deposits_credited,
        result.total_yield_cents / 100,
    )

    if result.credited:
        log.info("Detalhes dos créditos:")
        for item in result.credited:
            log.info(
                "  Aporte %s | parcela %d | principal R$ %.2f | "
                "rendimento creditado R$ %.2f | depositado em %s",
                item.principal_deposit_id,
                item.installment_number,
                item.principal_cents / 100,
                item.yield_credited_cents / 100,
                item.deposited_at,
            )

    log.info("=== Fim do job ===")
    return 0


def _parse_args() -> date:
    parser = argparse.ArgumentParser(
        description="Processa rendimentos da poupança para todos os aportes pendentes."
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Data de referência para o cálculo (padrão: hoje UTC)",
        default=None,
    )
    args = parser.parse_args()

    if args.date:
        try:
            return date.fromisoformat(args.date)
        except ValueError:
            print(f"[ERRO] Data inválida: {args.date!r}. Use o formato YYYY-MM-DD.")
            sys.exit(1)

    return datetime.now(timezone.utc).date()


if __name__ == "__main__":
    calc_date = _parse_args()
    exit_code = asyncio.run(_run(calc_date))
    sys.exit(exit_code)
