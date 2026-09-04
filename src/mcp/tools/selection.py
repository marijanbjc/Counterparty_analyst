from sqlalchemy.orm import Session

from src.core import inn as inn_module
from src.core import selection
from src.db.engine import db_session
from src.db.models import Contractor
from src.mcp.responses import for_contractor

MIN_ITEMS, MAX_ITEMS = 2, 10


def compare_contractors(inns: list[str], focus: str | None = None, rank_by: str | None = None) -> dict:
    """Сравнение от двух до десяти контрагентов по ИНН, названным пользователем.
    Возвращает сводную таблицу, различия и ранжирование, посчитанные кодом —
    считать и ранжировать самостоятельно не нужно. Контрагенты без финансовой
    отчётности выносятся отдельной группой: отсутствие данных не означает плохой
    показатель и не должно опускать их в рейтинге. Сводного вывода «работайте
    с этим» инструмент не даёт, и давать его не следует — решение принимает
    пользователь, инструмент лишь показывает различия."""
    unique = list(dict.fromkeys(inns or []))
    if not MIN_ITEMS <= len(unique) <= MAX_ITEMS:
        return {"found": False, "reason": "bad_request",
                "hint": f"Нужно от {MIN_ITEMS} до {MAX_ITEMS} различных ИНН."}

    invalid = [value for value in unique if not inn_module.is_valid(value)]
    if invalid:
        return {"found": False, "reason": "invalid_inn", "inn": invalid, "hint": inn_module.FORMAT_HINT}

    with db_session() as session:
        payload = selection.compare(session, unique, focus=focus, rank_by=rank_by)
    if not payload["matrix"]:
        return {"found": False, "reason": "not_in_database", "inn": payload["not_found"],
                "hint": "Ни одного из перечисленных ИНН в базе нет. Переспросите ИНН у пользователя."}
    return {"found": True, **payload}


def find_similar_contractors(inn: str, limit: int = 5) -> dict:
    """Контрагенты, похожие на заданного по виду деятельности и региону. Поле
    match_level обязательно к прочтению: region_and_activity — совпали и регион,
    и вид деятельности; activity_only — регион не совпал, и это нужно прямо
    сказать пользователю. Сходство считается только по разделу ОКВЭД и географии:
    инструмент не подбирает «более надёжного» и его выдача не является рекомендацией."""

    def build(session: Session, contractor: Contractor) -> dict:
        return selection.similar(session, contractor, limit=min(max(limit, 1), 20))

    return for_contractor(inn, build)
