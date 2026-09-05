"""Подсказки следующего шага — client_path_ideas.md §4.

После ответа клиент оставался в тупике: чтобы продолжить, надо было самому
придумать вопрос. Подсказки собираются кодом по факт-пакету, который уже
на руках: ни обращения к модели, ни единого токена.

Каждая подсказка несёт `kind`: "prompt" уходит в чат сразу, "draft" ложится
в поле ввода (клиенту надо дописать второй ИНН), "action" запускает сценарий
интерфейса.
"""

from typing import Any

# prompt — отправляется сразу: вопрос уже полный.
# draft  — подставляется в поле: клиенту надо дописать второй ИНН.
# action — запускает свой сценарий интерфейса.
PROMPT = "prompt"
DRAFT = "draft"
ACTION = "action"

ALTERNATIVES = "alternatives"

# Больше трёх подсказок читаются как меню, а не как продолжение разговора.
LIMIT = 3


def _item(code: str, label: str, kind: str = PROMPT, prompt: str | None = None) -> dict[str, Any]:
    return {"code": code, "label": label, "kind": kind, "prompt": prompt}


def for_report(pack: dict[str, Any], verdict: str | None) -> list[dict[str, Any]]:
    """Подсказки после разбора одного контрагента.

    Порядок — по важности находки, а не по порядку проверок: первым идёт то,
    что сильнее всего меняет решение клиента.
    """
    inn = pack.get("inn") or ""
    status = pack.get("legal_status") or {}
    financials = pack.get("financials") or {}
    execproc = pack.get("execution_proceedings") or {}
    items: list[dict[str, Any]] = []

    critical = status.get("severity") == "critical"
    if critical or verdict == "Не рекомендуется":
        # §7: подбор альтернативы — самая сильная из подсказок. Клиент остался
        # без контрагента, и продолжение разговора для него важнее разбора.
        items.append(_item(ALTERNATIVES, "Найти похожих без таких рисков", kind=ACTION))

    if critical:
        items.append(
            _item(
                "legal_meaning",
                "Что это значит для моего платежа",
                prompt=f"Что правовой статус контрагента {inn} значит для платежа в его адрес?",
            )
        )

    if (execproc.get("active") or 0) > 0:
        items.append(
            _item(
                "debt_scale",
                "Насколько велики взыскания",
                prompt=f"Насколько велики действующие взыскания у контрагента {inn} на фоне его оборота?",
            )
        )

    if not financials.get("available"):
        items.append(
            _item(
                "ask_documents",
                "Что запросить у контрагента",
                prompt=f"Какие документы запросить у контрагента {inn}, чтобы закрыть пробелы в данных?",
            )
        )

    if (pack.get("related_companies_count") or 0) > 0:
        items.append(
            _item(
                "affiliations",
                "Показать владельцев и связи",
                prompt=f"Кто владеет компанией {inn} и какие организации с ней связаны?",
            )
        )

    # Сравнение уместно всегда, но это самый слабый повод — идёт последним
    # и только если более содержательных подсказок не набралось.
    # Единственная подсказка-черновик: второй ИНН знает только клиент.
    items.append(
        _item("compare", "Сравнить с другим контрагентом", kind=DRAFT, prompt=f"Сравни {inn} и ")
    )
    return items[:LIMIT]


def for_compare(packs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Подсказки после сравнения: углубиться в конкретного из уже разобранных."""
    return [
        _item(
            f"drill_{pack['inn']}",
            f"Разобрать подробнее: {pack['short_name']}",
            prompt=f"Разбери подробнее контрагента {pack['inn']}",
        )
        for pack in packs[:LIMIT]
    ]
