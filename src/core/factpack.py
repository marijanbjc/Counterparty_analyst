from sqlalchemy.orm import Session

from src.core import aggregates, discrepancy
from src.core import inn as inn_module
from src.core.roles import chapters_for
from src.db.contragents import repository
from src.db.models import Contractor

COMPACT = "compact"
FULL = "full"

OPTIONAL_PROFILE_FIELDS = ("staff", "email", "website", "phone", "address", "kpp", "company_size")
SOLE_PROPRIETOR_NOT_APPLICABLE = ("kpp", "cofounders", "share_capital")


def _missing(contractor: Contractor, has_financials: bool, financial_years: list[dict]) -> list[str]:
    skip = SOLE_PROPRIETOR_NOT_APPLICABLE if inn_module.entity_kind(contractor.inn) == "sole_proprietor" else ()
    missing = [name for name in OPTIONAL_PROFILE_FIELDS if name not in skip and getattr(contractor, name) is None]
    if not has_financials:
        missing.append("fin_reports")
    if not contractor.coefficients:
        missing.append("coefficients")
    missing += [f"profit_{row['year']}" for row in financial_years if row["profit"] is None]
    missing += [f"proceeds_{row['year']}" for row in financial_years if row["proceeds"] is None]
    return missing


def _verdict_basis(contractor: Contractor) -> dict:
    return {
        "risk_level": contractor.risk_level,
        "zsk_risk_level": contractor.zsk_risk_level,
        "disagreement": discrepancy.traffic_lights_disagree(contractor),
    }


def _factors(contractor: Contractor, session: Session, chapters: tuple[str, ...], with_names: bool) -> dict:
    rows = repository.get_factors(session, contractor.inn, chapters=chapters)
    result: dict = {"negative": [], "positive": []}
    for row in rows:
        item = {"code": row.code, "chapter": row.chapter}
        if with_names:
            item["name"] = row.name
        result[row.polarity].append(item)
    result["negative_shown"] = len(result["negative"])
    result["negative_total"] = contractor.negative_factors_count
    result["filtered_by_role"] = bool(chapters)
    return result


def build(session: Session, inn: str, mode: str = FULL, role: str | None = None) -> dict | None:
    contractor = repository.get_contractor(session, inn)
    if contractor is None:
        return None

    reports = repository.get_fin_reports(session, inn)
    financials = aggregates.financials(reports)
    revenue = aggregates.latest_revenue(reports)
    has_financials = bool(reports)
    chapters = chapters_for(role)

    pack = {
        "inn": contractor.inn,
        "ogrn": contractor.ogrn,
        "short_name": contractor.short_name,
        "as_of": aggregates.iso(contractor.report_date),
        "verdict_basis": _verdict_basis(contractor),
        "profile": {
            "status": contractor.status,
            "registered": aggregates.iso(contractor.registration_date),
            "age_years": contractor.years_from_registration,
            "company_size": contractor.company_size,
            "entity_kind": inn_module.entity_kind(contractor.inn),
            "main_okved": {"code": contractor.main_okved_code, "description": contractor.main_okved_description},
            "okved_count": contractor.okved_count,
        },
        "financials": {**financials, "latest_revenue": revenue, "coefficients": contractor.coefficients},
        "arbitration": aggregates.arbitration(contractor, repository.get_arbitration_years(session, inn)),
        "execution_proceedings": aggregates.execproc_summary(contractor),
        "risk_factors": _factors(contractor, session, chapters, with_names=mode == FULL),
        "discrepancies": discrepancy.detect(contractor, revenue, has_financials),
        "related_companies_count": repository.count_related(session, inn),
    }

    if mode == COMPACT:
        pack["arbitration"].pop("by_year", None)
        pack["missing_data"] = _missing(contractor, has_financials, financials["years"])
        return pack

    pack["full_name"] = contractor.full_name
    pack["profile"].update(
        {
            "address": contractor.address,
            "email": contractor.email,
            "website": contractor.website,
            "phone": contractor.phone,
            "staff": contractor.staff,
            "kpp": contractor.kpp,
            "okpo": contractor.okpo,
            "tax_systems": contractor.tax_systems,
            "branches_count": contractor.branches_count,
            "share_capital": contractor.share_capital,
            "auth_person": {
                "name": contractor.auth_person_name,
                "position": contractor.auth_person_position,
                "since": aggregates.iso(contractor.auth_person_date),
            },
        }
    )
    pack["financials"]["balance"] = aggregates.balance(reports)
    pack["execution_proceedings"] = aggregates.execution_proceedings(
        contractor,
        repository.get_top_execproc(session, inn, active_only=True, limit=5),
        repository.get_execproc_by_year(session, inn),
    )
    pack["cofounders"] = [
        {"name": row.name, "inn": row.founder_inn, "share": float(row.share) if row.share else None,
         "active": row.active}
        for row in repository.get_cofounders(session, inn)
    ]
    pack["missing_data"] = _missing(contractor, has_financials, financials["years"])
    if pack["profile"]["entity_kind"] == "sole_proprietor":
        pack["not_applicable"] = list(SOLE_PROPRIETOR_NOT_APPLICABLE)
    return pack


def build_many(session: Session, inns: list[str], role: str | None = None) -> list[dict]:
    packs = [build(session, inn, mode="compact", role=role) for inn in inns]
    return [pack for pack in packs if pack]
