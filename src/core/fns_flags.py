from src.db.models import ReputationalFactor

CHAPTERS = ("reestrs", "manager")

# Градация согласована с кейсодателем: блокировка счетов и массовость — повод
# уточнить, а не приговор; фиктивность и номинальность — критично.
SEVERITY = {
    "invalidAddress": "critical",
    "invalidRegistrationData": "critical",
    "invalidAuthpersonsData": "critical",
    "disqualifiedAuthpersons": "critical",
    "liquidationStatus": "critical",
    "fnsBlocking": "attention",
    "massAddress": "attention",
    "massAuthpersons": "attention",
    "dishonestProvider": "attention",
    "taxArrears": "attention",
    "taxReporting": "attention",
}


def build(factors: list[ReputationalFactor]) -> dict:
    flags: dict[str, dict] = {}
    for row in factors:
        if row.chapter not in CHAPTERS or not row.code:
            continue
        present = row.polarity == "negative"
        # Позитивный фактор с тем же кодом означает подтверждённое отсутствие метки,
        # поэтому он не должен затирать негативный.
        if row.code in flags and not present:
            continue
        flags[row.code] = {
            "code": row.code,
            "present": present,
            "name": row.name,
            "severity": SEVERITY.get(row.code, "attention") if present else "none",
        }

    items = sorted(flags.values(), key=lambda f: (not f["present"], f["code"]))
    return {
        "flags": items,
        "negative_count": sum(1 for f in items if f["present"]),
        "critical_count": sum(1 for f in items if f["severity"] == "critical"),
    }
