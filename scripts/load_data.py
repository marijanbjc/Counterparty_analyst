import hashlib
import json
from pathlib import Path
from typing import Any

from src.core.address import parse_region
from src.core.normalize import dig, normalize_code, to_date, to_decimal, to_int, to_text


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _phone(report: dict) -> str | None:
    for phone in report.get("phones") or []:
        number = "".join(filter(None, [to_text(phone.get("phoneCode")), to_text(phone.get("phoneNumber"))]))
        if number:
            return number
    return None


def _execproc_rows(inn: str, report: dict) -> list[dict]:
    return [
        {
            "inn": inn,
            "active": bool(item.get("active")),
            "number": to_text(item.get("number")),
            "date": to_date(item.get("date")),
            "amount": to_decimal(item.get("amount")),
        }
        for item in report.get("executionProceedings") or []
    ]


def _fin_rows(inn: str, report: dict) -> list[dict]:
    rows = []
    for item in report.get("finReports") or []:
        year = to_int(dig(item, "common", "year"))
        if year is None:
            continue
        rows.append(
            {
                "inn": inn,
                "year": year,
                "proceeds": to_int(dig(item, "common", "proceeds")),
                "profit": to_int(dig(item, "common", "profit")),
                "total_assets": to_int(dig(item, "assets", "totalAssets")),
                "current_assets": to_int(dig(item, "assets", "currentAssets", "total")),
                "stocks": to_int(dig(item, "assets", "currentAssets", "stocks")),
                "receivables": to_int(dig(item, "assets", "currentAssets", "receivables")),
                "bankroll": to_int(dig(item, "assets", "currentAssets", "bankroll")),
                "uncurrent_assets": to_int(dig(item, "assets", "uncurrentAssets", "total")),
                "fixed_assets": to_int(dig(item, "assets", "uncurrentAssets", "fixedAssets")),
                "total_liabilities": to_int(dig(item, "liabilities", "totalLiabilities")),
                "capitals": to_int(dig(item, "liabilities", "capitals")),
                "long_term_total": to_int(dig(item, "liabilities", "longTermDuties", "total")),
                "long_term_others": to_int(dig(item, "liabilities", "longTermDuties", "others")),
                "short_term_total": to_int(dig(item, "liabilities", "shortTermLiabilities", "total")),
                "borrowed_funds": to_int(dig(item, "liabilities", "shortTermLiabilities", "borrowedFunds")),
                "accounts_payable": to_int(dig(item, "liabilities", "shortTermLiabilities", "accountsPayable")),
            }
        )
    return rows


def _factor_rows(inn: str, report: dict) -> list[dict]:
    risks = report.get("reputationalRisks") or {}
    return [
        {
            "inn": inn,
            "polarity": polarity,
            "code": normalize_code(item.get("code")),
            "chapter": to_text(item.get("chapter")),
            "name": to_text(item.get("name")),
        }
        for polarity in ("negative", "positive")
        for item in risks.get(polarity) or []
    ]


def _contractor_row(record: dict, execproc: list[dict], negative_count: int) -> dict:
    report = record["report"]
    base = report.get("baseInfo") or {}
    founders = report.get("foundersInfo") or {}
    auth = founders.get("authPerson") or {}
    activity = report.get("kindsOfActivityInfo") or {}
    main_activity = activity.get("mainKindOfActivity") or {}
    arbitration = report.get("arbitrationByStatus") or {}
    active = [item for item in execproc if item["active"]]

    return {
        "inn": to_text(base.get("inn")),
        "ogrn": to_text(base.get("ogrn")),
        "short_name": to_text(base.get("shortName")) or "",
        "full_name": to_text(base.get("fullName")) or "",
        "report_date": to_date(report.get("reportDate")),
        "risk_level": to_text(base.get("riskLevel")),
        "zsk_risk_level": to_text(report.get("zskRiskLevel")),
        "status": to_text(dig(report, "status", "status")),
        "status_reason": to_text(dig(report, "status", "reasonName")),
        "registration_date": to_date(dig(base, "registrationInfo", "registrationDate")),
        "years_from_registration": to_int(dig(base, "registrationInfo", "yearsFromRegistration")),
        "kpp": to_text(base.get("kpp")),
        "okpo": to_text(base.get("okpo")),
        "address": to_text(base.get("address")),
        "region": parse_region(to_text(base.get("address"))),
        "email": to_text(base.get("email")),
        "website": to_text(base.get("website")),
        "phone": _phone(report),
        "company_size": to_text(base.get("companySize")),
        "staff": to_text(base.get("staff")),
        "share_capital": to_int(founders.get("shareCapital")),
        "auth_person_name": to_text(auth.get("name")),
        "auth_person_inn": to_text(auth.get("inn")),
        "auth_person_position": to_text(auth.get("positionName")),
        "auth_person_date": to_date(auth.get("positionDate")),
        "main_okved_code": to_text(main_activity.get("code")),
        "main_okved_description": to_text(main_activity.get("description")),
        "okved_count": (1 if main_activity else 0) + len(activity.get("otherKindsOfActivity") or []),
        "tax_systems": [t for t in (to_text(i.get("shortName")) for i in report.get("taxSystem") or []) if t],
        "branches_count": to_int(dig(report, "branchesInfo", "branchesCount")) or 0,
        "execproc_total": len(execproc),
        "execproc_active": len(active),
        "execproc_total_amount": sum((i["amount"] for i in execproc if i["amount"]), start=to_decimal(0)),
        "execproc_active_amount": sum((i["amount"] for i in active if i["amount"]), start=to_decimal(0)),
        "negative_factors_count": negative_count,
        "arbitration_count": to_int(arbitration.get("commonCount")),
        "arbitration_amount": to_decimal(arbitration.get("commonAmount")),
        "arbitration_by_status": arbitration or None,
        "coefficients": report.get("coefficient") or None,
        "raw": report,
    }


def parse_snapshot(path: Path) -> dict[str, list[dict]]:
    records: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    parsed: dict[str, list[dict]] = {
        "contractors": [],
        "fin_reports": [],
        "execution_proceedings": [],
        "arbitration_by_year": [],
        "reputational_factors": [],
        "related_companies": [],
        "cofounders": [],
    }

    for record in records:
        report = record.get("report") or {}
        inn = to_text(dig(report, "baseInfo", "inn"))
        if not inn:
            continue

        execproc = _execproc_rows(inn, report)
        factors = _factor_rows(inn, report)
        negative = sum(1 for item in factors if item["polarity"] == "negative")

        parsed["contractors"].append(_contractor_row(record, execproc, negative))
        parsed["execution_proceedings"].extend(execproc)
        parsed["reputational_factors"].extend(factors)
        parsed["fin_reports"].extend(_fin_rows(inn, report))

        for item in report.get("arbitrationCases") or []:
            year = to_int(item.get("year"))
            if year is None:
                continue
            parsed["arbitration_by_year"].append(
                {
                    "inn": inn,
                    "year": year,
                    "plaintiff_count": to_int(item.get("plaintiffCount")),
                    "plaintiff_amount": to_decimal(item.get("plaintiffAmount")),
                    "defendant_count": to_int(item.get("defendantCount")),
                    "defendant_amount": to_decimal(item.get("defendantAmount")),
                }
            )

        for item in report.get("relatedCompanies") or []:
            parsed["related_companies"].append(
                {
                    "inn": inn,
                    "related_inn": to_text(item.get("inn")),
                    "related_ogrn": to_text(item.get("ogrn")),
                    "name": to_text(item.get("name")),
                    "registration_date": to_date(item.get("registrationDate")),
                    "auth_person_name": to_text(item.get("authPersonName")),
                    "auth_person_position": to_text(item.get("authPersonPosition")),
                }
            )

        for item in (report.get("foundersInfo") or {}).get("cofounders") or []:
            parsed["cofounders"].append(
                {
                    "inn": inn,
                    "name": to_text(item.get("name")),
                    "founder_inn": to_text(item.get("inn")),
                    "amount": to_int(item.get("amount")),
                    "share": to_decimal(item.get("share")),
                    "date_from": to_date(item.get("dateFrom")),
                    "active": bool(item.get("active")),
                }
            )

    return parsed


def load(force: bool = False, dry_run: bool = False) -> tuple[dict[str, int], bool]:
    from src.config.settings import get_settings

    settings = get_settings()
    path = settings.snapshot_file
    if not path.exists():
        raise FileNotFoundError(
            f"Снапшот не найден: {path}\n"
            "Файл не хранится в репозитории — положите его локально перед загрузкой."
        )

    parsed = parse_snapshot(path)
    counts = {name: len(rows) for name, rows in parsed.items()}
    if dry_run:
        return counts, False

    from sqlalchemy import delete, select

    from src.db.engine import create_tables, db_session
    from src.db.models import (
        ArbitrationByYear,
        Cofounder,
        Contractor,
        ExecutionProceeding,
        FinReport,
        RelatedCompany,
        ReputationalFactor,
        SnapshotMeta,
    )

    create_tables()
    digest = fingerprint(path)

    with db_session() as session:
        existing = session.execute(select(SnapshotMeta).order_by(SnapshotMeta.id.desc()).limit(1)).scalar_one_or_none()
        if existing and existing.fingerprint == digest and not force:
            return counts, True

        for model in (
            ExecutionProceeding,
            ReputationalFactor,
            RelatedCompany,
            Cofounder,
            ArbitrationByYear,
            FinReport,
            Contractor,
            SnapshotMeta,
        ):
            session.execute(delete(model))

        session.bulk_insert_mappings(Contractor, parsed["contractors"])
        session.bulk_insert_mappings(FinReport, parsed["fin_reports"])
        session.bulk_insert_mappings(ExecutionProceeding, parsed["execution_proceedings"])
        session.bulk_insert_mappings(ArbitrationByYear, parsed["arbitration_by_year"])
        session.bulk_insert_mappings(ReputationalFactor, parsed["reputational_factors"])
        session.bulk_insert_mappings(RelatedCompany, parsed["related_companies"])
        session.bulk_insert_mappings(Cofounder, parsed["cofounders"])
        session.add(SnapshotMeta(fingerprint=digest, record_count=len(parsed["contractors"])))

    return counts, False
