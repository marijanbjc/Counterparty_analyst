"""Системный промпт и схемы ответа (§5, §9).

Формат просим промптом, а не response_format: Groq буферизует любой структурированный
вывод и отдаёт готовый JSON одним куском (замерено, §13.2). Схема остаётся здесь же —
кодом мы проверяем форму сами и падаем на json_schema strict только последней попыткой.
"""

import json
from typing import Any

ANSWER = "answer"
SUMMARY = "summary"
ANALYSIS = "analysis"
KEY_RISKS = "key_risks"

RULES = """Ты — ассистент банка по проверке контрагентов. Правила работы:
1. Использовать только переданные данные. Нет в них — «таких данных в отчёте нет».
2. Не считать самому: производные значения уже посчитаны.
3. null — данных нет, это не ноль. "not_applicable" — поле неприменимо к ИП.
4. Вердикт передан на вход и обсуждению не подлежит — его нужно объяснить, а не пересмотреть. Оценка ЗСК упоминается отдельно и с вердиктом не смешивается.
5. При непустых discrepancies или legal_status.severity = "critical" — сказать об этом обязательно, даже когда светофор зелёный.
6. Различать действующие взыскания и историю: разрыв доходит до двух порядков.
7. Про арбитраж — только агрегатами; отдельные дела не описывать, их нет в источнике.
8. Указывать дату актуальности as_of.
9. Не давать указаний «работать» или «не работать»: подсвечивать риски и аккуратно рекомендовать. Решение принимает пользователь.
10. Не раскрывать полноту базы: никаких «известно N из M» и долей заполненности.
11. Имена полей источника допустимы в analysis, запрещены в answer.
12. Писать «ЗСК», не «ZSK». Доли переводить в проценты: не «0,0109», а «1 %»."""

# Порядок ключей — не оформление, а несущая конструкция: потоковый извлекатель
# (stream_json.FirstFieldExtractor) читает значение ПЕРВОГО ключа. Если answer
# перестанет быть первым, стриминг молча выключится, и ошибки при этом не будет.
REPLY_KEYS = (ANSWER,)
REPORT_KEYS = (ANSWER, SUMMARY, ANALYSIS, KEY_RISKS)

_FORMAT = (
    "Ответь одним JSON-объектом с ключами {keys} — строго в этом порядке, "
    "без markdown-обёртки, без пояснений до и после объекта."
)

_REPLY_SHAPE = f'{ANSWER} — реплика в чат, 2–4 предложения, без имён полей источника'
_REPORT_SHAPE = (
    f"{ANSWER} — реплика в чат, 3–6 предложений, без имён полей источника; "
    f"{SUMMARY} — 1–2 строки, попадут в сводку сессии; "
    f"{ANALYSIS} — подробный разбор, здесь имена полей источника допустимы; "
    f"{KEY_RISKS} — список строк, каждая строка — один риск."
)


def _schema(keys: tuple[str, ...]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        key: {"type": "array", "items": {"type": "string"}} if key == KEY_RISKS else {"type": "string"}
        for key in keys
    }
    return {
        "name": "contractor_reply",
        "schema": {
            "type": "object",
            "properties": properties,
            "required": list(keys),
            "additionalProperties": False,
        },
    }


REPLY_SCHEMA = _schema(REPLY_KEYS)
REPORT_SCHEMA = _schema(REPORT_KEYS)


def system(keys: tuple[str, ...]) -> str:
    shape = _REPORT_SHAPE if len(keys) > 1 else _REPLY_SHAPE
    return f"{RULES}\n\n{_FORMAT.format(keys=', '.join(keys))}\n{shape}"


def analyze_block(message: str, verdict: dict[str, Any], fact_pack: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Вопрос пользователя: {message}",
            _verdict_line(verdict),
            f"Факт-пакет контрагента (ИНН {fact_pack['inn']}):",
            json.dumps(fact_pack, ensure_ascii=False),
        ]
    )


def compare_block(message: str, verdicts: list[dict[str, Any]], payload: dict[str, Any]) -> str:
    lines = [f"Вопрос пользователя: {message}", "Вердикты посчитаны кодом, пересматривать их нельзя:"]
    lines += [f"— ИНН {item['inn']}: {item['verdict']}." for item in verdicts]
    lines.append("Сводка сравнения, посчитанная кодом:")
    lines.append(json.dumps(payload, ensure_ascii=False))
    lines.append(
        "Сводного вывода «работайте с этим» не давай: инструмент показывает различия, "
        "выбор делает пользователь."
    )
    return "\n".join(lines)


def clarify_block(message: str) -> str:
    return (
        f"Вопрос пользователя: {message}\n"
        "Отвечай по разобранному в этой сессии. Нового отчёта не делай. "
        "Если для ответа нужных данных в контексте нет — так и скажи и попроси ИНН."
    )


def _verdict_line(verdict: dict[str, Any]) -> str:
    line = f"Вердикт, посчитанный кодом: {verdict['verdict']}. Объясни его, не пересматривай."
    if verdict.get("escalated"):
        line += f" Вердикт повышен из-за правового статуса: {verdict['reason']}."
    return line
