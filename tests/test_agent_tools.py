import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, patch
from uuid import uuid4

from src.agent import catalog, dispatcher, llm, pipeline, prefetch, prompts, router
from src.agent.limiter import TokenRateLimiter
from src.mcp import toolsets
from src.mcp.advanced import charts
from src.webapp.schemas import MessageResponse


class ToolCatalogTests(unittest.TestCase):
    def test_openai_schema_preserves_required_arguments(self) -> None:
        [tool] = catalog.openai_tools(["get_basic_info"])

        function = tool["function"]
        self.assertEqual(function["name"], "get_basic_info")
        self.assertIn("inn", function["parameters"]["required"])
        self.assertFalse(function["parameters"]["additionalProperties"])

    def test_unknown_catalog_names_are_not_exposed(self) -> None:
        self.assertEqual(catalog.openai_tools(["does_not_exist"]), [])


class DispatcherTests(unittest.TestCase):
    def test_rejects_tool_not_offered_to_model(self) -> None:
        result, harvested, loaded = dispatcher.dispatch(
            "get_financials",
            {"inn": "7707083893"},
            {"7707083893"},
            (),
            {"load_tools"},
        )

        self.assertEqual(result["reason"], "tool_not_permitted")
        self.assertEqual(harvested, set())
        self.assertEqual(loaded, ())

    def test_load_tools_tracks_area_for_next_resolution(self) -> None:
        result, _, loaded = dispatcher.dispatch(
            "load_tools",
            {"area": "finance"},
            set(),
            (),
            {"load_tools"},
        )

        self.assertIn("get_financials", result["loaded"])
        self.assertEqual(loaded, ("finance",))
        resolved = toolsets.resolve("legal", "суды", loaded)
        self.assertIn("get_financials", resolved)

    def test_blocks_valid_inn_outside_session_before_call(self) -> None:
        result, harvested, _ = dispatcher.dispatch(
            "get_basic_info",
            {"inn": "7707083893"},
            set(),
            (),
            {"get_basic_info"},
        )

        self.assertEqual(result["reason"], "inn_not_in_session")
        self.assertEqual(result["inn"], ["7707083893"])
        self.assertEqual(harvested, set())

    def test_unknown_area_is_not_marked_loaded(self) -> None:
        result, _, loaded = dispatcher.dispatch(
            "load_tools",
            {"area": "unknown"},
            set(),
            (),
            {"load_tools"},
        )

        self.assertEqual(result["reason"], "unknown_area")
        self.assertEqual(loaded, ())

    def test_unrelated_items_do_not_expand_whitelist(self) -> None:
        harvested = dispatcher._harvest(
            "some_future_tool",
            {"inn": "7707083893", "items": [{"inn": "5032257375"}]},
        )

        self.assertEqual(harvested, {"7707083893"})


class PromptTests(unittest.TestCase):
    def test_role_and_tool_rules_are_both_present(self) -> None:
        text = prompts.system(prompts.REPLY_KEYS, role="legal", with_tools=True)

        self.assertIn("юридические риски", text)
        self.assertIn("Доступны инструменты", text)


class ToolCallBufferTests(unittest.TestCase):
    def test_reassembles_fragmented_arguments(self) -> None:
        buffer = llm._ToolCallBuffer()
        buffer.feed([
            {"index": 0, "id": "call-1", "function": {"name": "get_basic_info", "arguments": '{"inn":"770'}},
        ])
        buffer.feed([
            {"index": 0, "function": {"arguments": '7083893"}'}},
        ])

        self.assertEqual(
            buffer.finished(),
            ({"id": "call-1", "name": "get_basic_info", "arguments": {"inn": "7707083893"}},),
        )

    def test_invalid_json_is_not_treated_as_structured_answer(self) -> None:
        data, error = llm._decode_content('{"answer":')

        self.assertEqual(data, {})
        self.assertEqual(error, "невалидный JSON")

    def test_request_estimate_includes_tool_call_arguments(self) -> None:
        plain = llm._estimate_request([{"role": "assistant", "content": None}], None)
        with_call = llm._estimate_request(
            [{
                "role": "assistant",
                "content": None,
                "tool_calls": [{"function": {"name": "tool", "arguments": '{"large":"payload"}'}}],
            }],
            None,
        )

        self.assertGreater(with_call, plain)


class InputValidationTests(unittest.TestCase):
    def test_empty_chart_target_returns_bad_request(self) -> None:
        result = charts.build_chart([], "revenue_profit")

        self.assertEqual(result["reason"], "bad_request")

    def test_unknown_dataset_is_reported(self) -> None:
        result = prefetch.collect(["unknown"], "7707083893", 2)

        self.assertEqual(result.unknown, ("unknown",))
        self.assertIn("unknown", result.notice or "")


class RouterTests(unittest.TestCase):
    def test_four_scenarios_are_deterministic(self) -> None:
        ask = router.choose("check", False, 0, 20, 3)
        clarify = router.choose("what about courts", True, 0, 20, 3)
        analyze = router.choose("5032257375", False, 0, 20, 3)
        compare = router.choose("5032257375 7707083893", False, 0, 20, 3)

        self.assertEqual(ask.scenario, router.ASK)
        self.assertEqual(clarify.scenario, router.CLARIFY)
        self.assertEqual(analyze.scenario, router.ANALYZE)
        self.assertEqual(compare.scenario, router.COMPARE)

    def test_quota_is_checked_before_routing(self) -> None:
        route = router.choose("5032257375", False, 20, 20, 3)

        self.assertEqual(route.scenario, router.QUOTA_EXCEEDED)
        self.assertFalse(route.needs_llm)


class ContextBudgetTests(unittest.TestCase):
    def test_large_tool_result_is_replaced_with_valid_json(self) -> None:
        messages = [
            {"role": "system", "content": "rules"},
            {"role": "tool", "tool_call_id": "1", "content": '{"rows":"' + "x" * 5000 + '"}'},
        ]
        budget = pipeline._request_tokens(
            [{"role": "system", "content": "rules"}],
            None,
        ) + 100

        pipeline._compact_tool_results(messages, None, budget)

        self.assertIn("tool_result_too_large", messages[-1]["content"])
        self.assertLessEqual(pipeline._request_tokens(messages, None), budget)


class PersistenceTests(unittest.TestCase):
    def test_compare_links_existing_and_saves_missing_analyses(self) -> None:
        session_id = uuid4()
        existing = object()
        plan = SimpleNamespace(
            packs=[{"inn": "5032257375"}, {"inn": "7707083893"}],
            role_preset="general",
            session_id=session_id,
        )
        baseline = {"verdict": "v", "summary": "s", "analysis": "a"}

        with (
            patch.object(
                pipeline.analyses_repository,
                "get",
                side_effect=[existing, None],
            ),
            patch.object(pipeline.analyses_repository, "link_to_session") as link,
            patch.object(pipeline.analyses_repository, "save") as save,
            patch.object(pipeline.report_builder, "build", return_value={}),
            patch.object(pipeline.verdicts, "apply", return_value=baseline),
        ):
            pipeline._persist_comparison(object(), plan)

        link.assert_called_once_with(ANY, session_id, existing)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(save.call_args.kwargs["inn"], "7707083893")


class ApiSchemaTests(unittest.TestCase):
    def test_private_message_metadata_is_not_exposed(self) -> None:
        message = MessageResponse.model_validate(
            {
                "id": 1,
                "session_id": uuid4(),
                "role": "assistant",
                "content": "ok",
                "tokens": 1,
                "meta": {"scenario": "clarify", "_allowed_inns": ["7707083893"]},
                "created_at": datetime.now(timezone.utc),
            }
        )

        self.assertEqual(message.meta, {"scenario": "clarify"})


class LimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_calls_are_serialized(self) -> None:
        limiter = TokenRateLimiter(100)
        order: list[str] = []

        async def call(name: str) -> None:
            async with limiter.serialized_call():
                order.append(f"{name}:start")
                await asyncio.sleep(0)
                order.append(f"{name}:end")

        await asyncio.gather(call("first"), call("second"))

        self.assertEqual(order, ["first:start", "first:end", "second:start", "second:end"])


if __name__ == "__main__":
    unittest.main()
