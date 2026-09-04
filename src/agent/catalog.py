"""Каталог инструментов агента: те же функции, что регистрирует MCP-сервер.

Схемы для модели собираются из сигнатуры и docstring. Какие имена попадут
в конкретный шаг, решает toolsets.resolve(), а не этот модуль.
"""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable
from typing import Any, Union, get_args, get_origin

from src.mcp.advanced import analysis, charts, questions
from src.mcp.server import load_tools
from src.mcp.tools import activity, finance, legal, profile, relations, selection, summary

FUNCTIONS: dict[str, Callable[..., dict]] = {
    "get_basic_info": profile.get_basic_info,
    "get_legal_status": profile.get_legal_status,
    "get_fns_flags": profile.get_fns_flags,
    "get_ownership": profile.get_ownership,
    "get_financials": finance.get_financials,
    "get_balance_sheet": finance.get_balance_sheet,
    "get_liabilities": finance.get_liabilities,
    "get_financial_ratios": finance.get_financial_ratios,
    "get_debt_burden": finance.get_debt_burden,
    "get_arbitration": legal.get_arbitration,
    "get_execution_proceedings": legal.get_execution_proceedings,
    "get_activity": activity.get_activity,
    "get_licenses": activity.get_licenses,
    "get_inspections": activity.get_inspections,
    "get_procurements": activity.get_procurements,
    "get_affiliations": relations.get_affiliations,
    "get_risk_factors": summary.get_risk_factors,
    "get_contractor_full": summary.get_contractor_full,
    "compare_contractors": selection.compare_contractors,
    "find_similar_contractors": selection.find_similar_contractors,
    "run_focused_analysis": analysis.run_focused_analysis,
    "build_chart": charts.build_chart,
    "draft_followup_questions": questions.draft_followup_questions,
    "load_tools": load_tools,
}


def openai_tools(names: list[str]) -> list[dict[str, Any]]:
    return [_openai_tool(FUNCTIONS[name]) for name in names if name in FUNCTIONS]


def _openai_tool(function: Callable[..., dict]) -> dict[str, Any]:
    hints = inspect.get_annotations(function, eval_str=True)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in inspect.signature(function).parameters.items():
        schema = _json_schema(hints.get(name, str))
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
        properties[name] = schema
    return {
        "type": "function",
        "function": {
            "name": function.__name__,
            "description": inspect.getdoc(function) or function.__name__,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _json_schema(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType):
        useful = [item for item in args if item is not type(None)]
        if len(useful) == 1:
            return _json_schema(useful[0])
        return {"anyOf": [_json_schema(item) for item in useful]}
    if origin is list:
        return {"type": "array", "items": _json_schema(args[0]) if args else {"type": "string"}}
    return {"type": {str: "string", int: "integer", bool: "boolean", float: "number"}.get(annotation, "string")}
