from sqlalchemy.orm import Session

from src.core import aggregates, debt
from src.core.normalize import to_decimal
from src.db.contragents import repository
from src.db.models import Contractor, FinReport
from src.mcp.responses import factor_items, for_contractor

FINANCE_CHAPTER = ("finance",)


def _finance_factors(session: Session, inn: str) -> list[dict]:
    return factor_items(repository.get_factors(session, inn, FINANCE_CHAPTER))


def _years(reports: list[FinReport], year: int | None) -> list[FinReport]:
    ordered = sorted(reports, key=lambda r: r.year)
    return [r for r in ordered if year is None or r.year == year]


def get_financials(inn: str, year_from: int | None = None, year_to: int | None = None) -> dict:
    """Отчёт о финансовых результатах: выручка и прибыль по годам плюс тренд, посчитанный
    кодом. Прибыль может быть отрицательной — это убыток. Пустое значение прибыли
    означает, что показатель не раскрыт: это не ноль и не убыток, и так примерно
    в половине отчётов. Если available = false, финансовой отчётности нет вовсе —
    не интерпретируй это как отсутствие деятельности или как плохой показатель.
    Тренд уже посчитан, выводить его самостоятельно из чисел не нужно."""

    def build(session: Session, contractor: Contractor) -> dict:
        reports = repository.get_fin_reports(session, contractor.inn, year_from, year_to)
        payload = aggregates.financials(reports)
        missing = [f"proceeds_{r['year']}" for r in payload["years"] if r["proceeds"] is None]
        missing += [f"profit_{r['year']}" for r in payload["years"] if r["profit"] is None]
        if not reports:
            missing.append("fin_reports")
        return {**payload, "missing": missing, "factors": _finance_factors(session, contractor.inn)}

    return for_contractor(inn, build)


def get_balance_sheet(inn: str, year: int | None = None) -> dict:
    """Активы и собственный капитал по годам: валюта баланса, оборотные и внеоборотные
    активы, запасы, дебиторская задолженность, денежные средства, основные средства,
    чистые активы. Отвечает на вопрос об обеспеченности, в отличие от get_financials,
    который про оборот. Флаг negative_net_assets означает, что обязательства превышают
    активы — существенный сигнал, который банковский светофор не учитывает,
    и о нём нужно сказать прямо."""

    def build(session: Session, contractor: Contractor) -> dict:
        reports = _years(repository.get_fin_reports(session, contractor.inn), year)
        years = [
            {
                "year": r.year,
                "total_assets": r.total_assets,
                "net_assets": r.capitals,
                "current_assets": r.current_assets,
                "uncurrent_assets": r.uncurrent_assets,
                "stocks": r.stocks,
                "receivables": r.receivables,
                "bankroll": r.bankroll,
                "fixed_assets": r.fixed_assets,
            }
            for r in reports
        ]
        latest = years[-1] if years else None
        return {
            "available": bool(years),
            "years": years,
            "negative_net_assets": bool(latest and latest["net_assets"] is not None and latest["net_assets"] < 0),
            "missing": [] if years else ["fin_reports"],
            "factors": _finance_factors(session, contractor.inn),
        }

    return for_contractor(inn, build)


def get_liabilities(inn: str, year: int | None = None) -> dict:
    """Обязательства контрагента: кредиторская задолженность, заёмные средства,
    краткосрочные и долгосрочные обязательства. Только обязательства; активы
    и собственный капитал — в get_balance_sheet. Соотношение кредиторской
    задолженности к заёмным средствам показывает, за чей счёт живёт компания:
    банковские кредиты или отсрочка от поставщиков. Само соотношение уже посчитано,
    считать его не нужно."""

    def build(session: Session, contractor: Contractor) -> dict:
        reports = _years(repository.get_fin_reports(session, contractor.inn), year)
        years = []
        for r in reports:
            # Отношение считаем только при известных обеих величинах: подстановка нуля
            # вместо отсутствия превратила бы «неизвестно» в «кредитов нет».
            ratio = (
                round(r.accounts_payable / r.borrowed_funds, 4)
                if r.accounts_payable is not None and r.borrowed_funds
                else None
            )
            years.append(
                {
                    "year": r.year,
                    "total_liabilities": r.total_liabilities,
                    "accounts_payable": r.accounts_payable,
                    "borrowed_funds": r.borrowed_funds,
                    "short_term_total": r.short_term_total,
                    "long_term_total": r.long_term_total,
                    "long_term_others": r.long_term_others,
                    "payable_to_borrowed": ratio,
                }
            )
        return {
            "available": bool(years),
            "years": years,
            "missing": [] if years else ["fin_reports"],
            "factors": _finance_factors(session, contractor.inn),
        }

    return for_contractor(inn, build)


def get_financial_ratios(inn: str) -> dict:
    """Готовые финансовые коэффициенты из отчёта: устойчивость, платёжеспособность,
    рентабельность. Значения приходят из источника и самостоятельно не рассчитываются.
    Если блока нет — данных нет, и выводить коэффициенты из баланса запрещено.
    Точные формулы расчёта банк не раскрыл, поэтому называй значение и его смысл,
    но не выноси нормативную оценку «хорошо» или «плохо»."""

    def build(session: Session, contractor: Contractor) -> dict:
        source = contractor.coefficients or {}
        if not source:
            return {"available": False, "year": None, "missing": ["coefficients"]}

        def value(name: str) -> float | None:
            parsed = to_decimal(source.get(name))
            return float(parsed) if parsed is not None else None

        payload = {name: value(name) for name in ("sustainability", "solvency", "profitability")}
        return {
            "available": True,
            "year": int(source["year"]) if source.get("year") else None,
            **payload,
            "missing": [name for name, item in payload.items() if item is None],
        }

    return for_contractor(inn, build)


def get_debt_burden(inn: str) -> dict:
    """Соотносит текущую долговую нагрузку с масштабом бизнеса и отвечает на вопрос,
    критичны эти долги или находятся в пределах погрешности. Текущий долг — это
    действующие исполнительные производства плюс открытый арбитраж, где контрагент
    выступает ответчиком; завершённые дела в него не входят. Сравнение идёт с чистыми
    активами и выручкой. Если comparable = false, соотносить не с чем: приводи
    абсолютные суммы и не оценивай их критичность. Одна и та же сумма для
    микропредприятия катастрофична, а для крупной компании находится в пределах
    погрешности — поэтому абсолютные пороги здесь неприменимы."""

    def build(session: Session, contractor: Contractor) -> dict:
        return debt.build(contractor, repository.get_fin_reports(session, contractor.inn))

    return for_contractor(inn, build)
