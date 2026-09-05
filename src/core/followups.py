"""Что запросить у контрагента — детерминированно из пробелов и негативных факторов.
LLM здесь не участвует: формулировки фиксированные (ARCHITECTURE.md)."""

TEMPLATES = {
    "legal_status_critical": (
        "Выписку из ЕГРЮЛ на текущую дату",
        "В реестре указана процедура прекращения или банкротства",
        "legal_status.status_reason",
    ),
    "no_financials": (
        "Бухгалтерский баланс и отчёт о финансовых результатах за последний год",
        "Финансовой отчётности в отчёте нет",
        "financials.available",
    ),
    "negative_net_assets": (
        "Пояснение по источникам покрытия обязательств",
        "Чистые активы отрицательны: обязательства превышают активы",
        "balance_sheet.net_assets",
    ),
    "execproc_active": (
        "Справку об отсутствии задолженности и пояснение по действующим взысканиям",
        "Есть действующие исполнительные производства",
        "execution_proceedings.active",
    ),
    "arbitration_pending": (
        "Пояснение по предмету и стадии незавершённых судебных споров",
        "Есть открытые арбитражные дела, где контрагент выступает ответчиком",
        "arbitration.as_defendant.pending_count",
    ),
    "fns_blocking": (
        "Пояснение по блокировке счёта и ожидаемый срок её снятия",
        "В реестрах ФНС отмечена блокировка счетов",
        "fns_flags.fnsBlocking",
    ),
    "invalid_address": (
        "Подтверждение фактического места нахождения: договор аренды или свидетельство о праве",
        "Адрес отмечен в реестре ФНС как недостоверный или массовый",
        "fns_flags.invalidAddress",
    ),
    "nominal_director": (
        "Документы, подтверждающие полномочия руководителя",
        "В реестре есть метка о номинальном руководителе или недостоверных данных о нём",
        "fns_flags.invalidAuthpersonsData",
    ),
    "mass_okved": (
        "Уточнение профильного вида деятельности по вашему предмету договора",
        "Отмечены коды ОКВЭД из перечня, характерного для фирм-однодневок",
        "activity.mass_okved",
    ),
}

ADDRESS_CODES = {"invalidAddress", "massAddress"}
DIRECTOR_CODES = {"invalidAuthpersonsData", "massAuthpersons"}


def build(*, legal_severity: str, has_financials: bool, negative_net_assets: bool,
          execproc_active: int, arbitration_pending: int, flag_codes: set[str],
          mass_okved: bool) -> list[dict]:
    triggers = []
    if legal_severity == "critical":
        triggers.append("legal_status_critical")
    if not has_financials:
        triggers.append("no_financials")
    if negative_net_assets:
        triggers.append("negative_net_assets")
    if execproc_active > 0:
        triggers.append("execproc_active")
    if arbitration_pending > 0:
        triggers.append("arbitration_pending")
    if "fnsBlocking" in flag_codes:
        triggers.append("fns_blocking")
    if flag_codes & ADDRESS_CODES:
        triggers.append("invalid_address")
    if flag_codes & DIRECTOR_CODES:
        triggers.append("nominal_director")
    if mass_okved:
        triggers.append("mass_okved")

    return [
        {"trigger": name, "question": TEMPLATES[name][0], "reason": TEMPLATES[name][1],
         "source_field": TEMPLATES[name][2]}
        for name in triggers
    ]
