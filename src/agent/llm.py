import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.agent.limiter import get_limiter
from src.agent.stream_json import FirstFieldExtractor
from src.agent.tokens import estimate
from src.config.settings import get_settings

ANSWER_FIELD = "answer"
SCHEMA_NAME = "response"
# Режим отвечает только за response_format запроса. Разбор ответа и извлечение
# answer включает schema: Groq не стримит структурированный вывод по токенам,
# поэтому MODE_TEXT + schema — это «формат просим промптом, поток сохраняем».
MODE_JSON_SCHEMA = "json_schema"
MODE_JSON_OBJECT = "json_object"
MODE_TEXT = "text"
COMPLETIONS_PATH = "/chat/completions"
RETRYABLE_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})
SSE_PREFIX = "data: "
SSE_DONE = "[DONE]"


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Result:
    data: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    # Непустой список — форма ответа разошлась со схемой, но дельты уже ушли
    # пользователю и повтор запрещён (§13.6). Решение за персистером.
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Failure:
    detail: str


@dataclass(frozen=True)
class ToolCalls:
    calls: tuple[dict[str, Any], ...]
    usage: dict[str, Any] = field(default_factory=dict)
    content: str | None = None


LlmEvent = Delta | Result | Failure | ToolCalls


class LlmError(RuntimeError):
    pass


async def stream(
    messages: list[dict],
    schema: dict | None,
    tpm_limit: int,
    expected_completion: int,
    mode: str = MODE_TEXT,
    effort: str | None = None,
    tools: list[dict] | None = None,
) -> AsyncIterator[LlmEvent]:
    """Куски поля answer по мере поступления, затем Result или Failure.

    Лестница §13.2: формат просим промптом и стримим; форму проверяем кодом;
    не сошлась при нулевом числе дельт — повтор; последняя попытка уходит
    на json_schema strict, где стриминг потерян, но форма гарантирована.

    expected_completion резервируется вместе с промптом: record() записывает
    prompt + completion, и без этого слагаемого окно занижается на коротких
    промптах, где ответ сопоставим с запросом.
    """
    settings = get_settings()
    limiter = get_limiter(tpm_limit)
    attempts = settings.llm_max_retries + 1
    detail = "ИИ-анализ временно недоступен."

    for attempt in range(attempts):
        last = attempt == attempts - 1
        # Последняя ступень лестницы формы обязана быть strict. Если предыдущие
        # ответы с tools были malformed, на страховочном запросе схемы tools
        # снимаются: Groq не гарантирует совместимость обоих режимов.
        strict_fallback = last and schema is not None and (attempt > 0 or not tools)
        active_tools = None if strict_fallback else tools
        call_mode = MODE_JSON_SCHEMA if strict_fallback else mode
        estimated = (
            _estimate_request(
                messages,
                schema if call_mode == MODE_JSON_SCHEMA else None,
                active_tools,
            )
            + expected_completion
        )
        async with limiter.serialized_call():
            await limiter.reserve(estimated)
            extractor = FirstFieldExtractor(ANSWER_FIELD) if schema is not None and not active_tools else None
            plain: list[str] = []
            usage: dict[str, Any] = {}
            tool_buffer = _ToolCallBuffer()
            streamed = False
            try:
                async for kind, payload in _read_stream(
                    settings, messages, schema, call_mode, effort, active_tools
                ):
                    if kind == "usage":
                        usage = payload
                        continue
                    if kind == "tool_calls":
                        tool_buffer.feed(payload)
                        continue
                    if extractor is None:
                        plain.append(payload)
                        text = payload if not tools else ""
                    else:
                        text = extractor.feed(payload)
                    if text:
                        streamed = True
                        yield Delta(text)
            except httpx.HTTPStatusError as exc:
                limiter.record(_spent(usage, estimated))
                if streamed or exc.response.status_code not in RETRYABLE_STATUSES:
                    yield Failure(_http_detail(exc))
                    return
                detail = _http_detail(exc)
                await limiter.backoff(attempt, _retry_after(exc.response))
                continue
            except httpx.HTTPError as exc:
                limiter.record(_spent(usage, estimated))
                if streamed:
                    yield Failure(f"Соединение с моделью прервано: {exc}.")
                    return
                detail = f"Модель недоступна: {exc}."
                await limiter.backoff(attempt)
                continue
            except BaseException:
                # Отмена HTTP-клиента не должна оставлять «pending» резерв:
                # следующий завершившийся вызов иначе запишет usage в чужую запись.
                limiter.record(_spent(usage, estimated))
                raise

            limiter.record(_spent(usage, estimated))

        if tool_buffer:
            yield ToolCalls(tool_buffer.finished(), usage, "".join(plain) or None)
            return

        if extractor is None:
            text = "".join(plain)
            data, parse_error = _decode_content(text)
            problems = check_shape(data, schema) if schema is not None else []
            if parse_error or problems:
                reasons = ([parse_error] if parse_error else []) + problems
                detail = "Форма ответа модели разошлась со схемой: " + "; ".join(reasons)
                if not last:
                    continue
                yield Failure(detail)
                return
            # Пока были доступны tools, content нельзя было отдавать заранее:
            # провайдер вправе прислать content и tool_calls в одном ответе.
            # После завершения известно, что вызовов нет — отдаём готовый answer.
            answer = data.get(ANSWER_FIELD)
            if active_tools and isinstance(answer, str) and answer:
                yield Delta(answer)
            yield Result(data, usage)
            return

        try:
            data = json.loads(extractor.buffered)
        except json.JSONDecodeError:
            detail = "Модель вернула неразбираемый ответ."
            if streamed or last:
                yield Failure(detail)
                return
            continue

        problems = check_shape(data, schema)
        if problems and not streamed:
            # Дельт не было — пользователю ничего не показано, повтор безопасен.
            detail = "Форма ответа модели разошлась со схемой: " + "; ".join(problems)
            if not last:
                continue
            yield Failure(detail)
            return

        if extractor.fell_back:
            # Стриминг на этом ходе потерян, ответ — нет: отдаём одним куском.
            answer = data.get(ANSWER_FIELD)
            if isinstance(answer, str) and answer:
                yield Delta(answer)
        yield Result(data, usage, tuple(problems))
        return

    yield Failure(detail)


async def complete(
    messages: list[dict],
    schema: dict | None,
    tpm_limit: int,
    expected_completion: int,
    mode: str = MODE_TEXT,
    effort: str | None = None,
    tools: list[dict] | None = None,
) -> dict:
    """Нестримящий режим — накопление того же потока, без второй HTTP-логики."""
    chunks: list[str] = []
    async for event in stream(messages, schema, tpm_limit, expected_completion, mode, effort, tools):
        if isinstance(event, Delta):
            chunks.append(event.text)
        elif isinstance(event, Failure):
            raise LlmError(event.detail)
        elif isinstance(event, ToolCalls):
            return {
                "tool_calls": event.calls,
                "usage": event.usage,
                "text": event.content or "".join(chunks),
            }
        else:
            return {"data": event.data, "usage": event.usage, "text": "".join(chunks)}
    raise LlmError("Модель не вернула ответ.")


async def _read_stream(
    settings: Any,
    messages: list[dict],
    schema: dict | None,
    mode: str,
    effort: str | None,
    tools: list[dict] | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if effort is not None:
        payload["reasoning_effort"] = effort
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        # json_schema и tools вместе Groq буферизует и часто игнорирует вызовы.
    else:
        response_format = _response_format(schema, mode)
        if response_format is not None:
            payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}

    async with httpx.AsyncClient(
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
    ) as client:
        async with client.stream(
            "POST", COMPLETIONS_PATH, json=payload, headers=headers
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith(SSE_PREFIX):
                    continue
                body = line[len(SSE_PREFIX) :].strip()
                if body == SSE_DONE:
                    break
                chunk = json.loads(body)
                if chunk.get("usage"):
                    yield "usage", chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    # delta.reasoning не читаем: ни в БД, ни пользователю оно не идёт.
                    calls = delta.get("tool_calls")
                    if calls:
                        yield "tool_calls", calls
                    text = delta.get("content")
                    if text:
                        yield "content", text


def check_shape(data: Any, schema: dict) -> list[str]:
    """Проверка ответа по схеме: только та вложенность, что есть в наших схемах."""
    if not isinstance(data, dict):
        return ["ответ не является объектом"]
    body = schema.get("schema", schema)
    properties = body.get("properties") or {}
    problems: list[str] = []
    for key in body.get("required") or list(properties):
        if key not in data:
            problems.append(f"нет поля {key}")
            continue
        expected = (properties.get(key) or {}).get("type")
        value = data[key]
        if expected == "string" and not (isinstance(value, str) and value.strip()):
            problems.append(f"{key}: ожидалась непустая строка")
        elif expected == "array":
            items = (properties[key].get("items") or {}).get("type")
            if not isinstance(value, list):
                problems.append(f"{key}: ожидался список")
            elif items == "string" and not all(isinstance(item, str) for item in value):
                problems.append(f"{key}: ожидался список строк")
            elif items == "object" and not all(isinstance(item, dict) for item in value):
                problems.append(f"{key}: ожидался список объектов")
    return problems


def _response_format(schema: dict | None, mode: str) -> dict[str, Any] | None:
    if mode == MODE_JSON_OBJECT:
        return {"type": "json_object"}
    if mode == MODE_JSON_SCHEMA and schema is not None:
        return {"type": "json_schema", "json_schema": _json_schema(schema)}
    return None


def _json_schema(schema: dict) -> dict[str, Any]:
    if "schema" in schema:
        return {"strict": True, **schema}
    return {"name": SCHEMA_NAME, "strict": True, "schema": schema}


def _estimate_request(messages: list[dict], schema: dict | None, tools: list[dict] | None = None) -> int:
    # Полная сериализация учитывает assistant.tool_calls, arguments и
    # tool_call_id на повторных шагах цикла.
    text = json.dumps(messages, ensure_ascii=False, default=str)
    if schema is not None:
        text += json.dumps(schema, ensure_ascii=False)
    if tools:
        text += json.dumps(tools, ensure_ascii=False)
    return estimate(text)


def _decode_content(text: str) -> tuple[dict[str, Any], str | None]:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return {ANSWER_FIELD: text}, None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return {}, "невалидный JSON"
    if not isinstance(data, dict):
        return {}, "ответ не является объектом"
    return data, None


class _ToolCallBuffer:
    def __init__(self) -> None:
        self._slots: dict[int, dict[str, str]] = {}

    def __bool__(self) -> bool:
        return bool(self._slots)

    def feed(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            index = int(item.get("index") or 0)
            slot = self._slots.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if item.get("id"):
                slot["id"] = str(item["id"])
            function = item.get("function") or {}
            if function.get("name"):
                slot["name"] = str(function["name"])
            if function.get("arguments"):
                slot["arguments"] += str(function["arguments"])

    def finished(self) -> tuple[dict[str, Any], ...]:
        calls = []
        for index, slot in sorted(self._slots.items()):
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                {
                    "id": slot["id"] or f"call_{index}",
                    "name": slot["name"],
                    "arguments": arguments,
                }
            )
        return tuple(calls)


def _spent(usage: dict[str, Any], estimated: int) -> int:
    return int(usage.get("total_tokens") or estimated)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _http_detail(exc: httpx.HTTPStatusError) -> str:
    if exc.response.status_code == 429:
        return "Лимит запросов к модели исчерпан, попробуйте позже."
    return f"Модель ответила ошибкой {exc.response.status_code}."
