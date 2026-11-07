import unittest
from unittest.mock import patch

from app.listener import VoiceListener
from app.llm_client import LLMClient
from app.pc_agent import PCAgent, hinted_tools_for_query


class HintedToolsTests(unittest.TestCase):

    def test_copilot_request_selects_gui_tools(self):
        hints = hinted_tools_for_query(
            "напиши в vs code github copilot чтобы он исправил "
            "ошибку в проекте python project9"
        )
        self.assertIn("keyboard_type", hints)
        self.assertIn("text_type", hints)
        self.assertIn("window_activate", hints)
        self.assertIn("app_launch", hints)
        self.assertIn("automation_copilot_fix", hints)

    def test_window_request_selects_window_tools(self):
        hints = hinted_tools_for_query("джарвис сверни окно браузера")
        self.assertIn("window_state", hints)
        self.assertIn("minimize_window", hints)

    def test_no_match_returns_empty(self):
        self.assertEqual(hinted_tools_for_query("привет"), [])

    def test_get_llm_tools_includes_hints(self):
        agent = PCAgent()
        tools = agent.get_llm_tools(
            "напиши в vs code copilot исправь ошибку"
        )
        names = {
            tool["function"]["name"] for tool in tools
        }
        self.assertIn("text_type", names)
        self.assertIn("app_launch", names)
        self.assertIn("run_powershell", names)
        self.assertIn("automation_copilot_fix", names)

    def test_get_llm_tools_respects_limit(self):
        agent = PCAgent()
        legacy_names = {
            tool["function"]["name"] for tool in agent.get_tools()
        }
        for limit in (20, 40):
            tools = agent.get_llm_tools(limit=limit)
            extra = [
                tool
                for tool in tools
                if tool["function"]["name"] not in legacy_names
            ]
            self.assertLessEqual(len(extra), max(limit, 20))

    def test_categories_filter(self):
        agent = PCAgent()
        categories = agent.registry.categories()
        self.assertTrue(categories)
        tools = agent.get_llm_tools(categories=categories[:2], limit=40)
        names = {
            tool["function"]["name"] for tool in tools
        }
        self.assertTrue(names)
        self.assertIn("run_powershell", names)

    def test_code_mode_categories_respect_provider_tool_limit(self):
        agent = PCAgent()
        query = "придумай как улучшить проект python project 9"
        categories = [
            category
            for category in (
                "dev",
                "apps",
                "windows",
                "input",
                "files",
                "screen",
                "automation",
                "processes",
            )
            if category in agent.registry.categories()
        ]

        tools = agent.get_llm_tools(query, categories=categories)
        names = {tool["function"]["name"] for tool in tools}

        self.assertLessEqual(len(tools), 128)
        self.assertIn("dev_run_python", names)
        self.assertIn("dev_tests", names)
        self.assertIn("automation_copilot_fix", names)


class PlanCategoriesTests(unittest.TestCase):

    def test_plan_categories_offline_returns_none(self):
        client = LLMClient(use_llm=False, api_key="")
        self.assertIsNone(
            client.plan_categories("джарвис сверни окно", ["windows"])
        )

    def test_plan_categories_parses_json(self):
        client = LLMClient(use_llm=True, api_key="test")

        def fake_request(payload, api_url=None, api_key=None):
            return {"content": 'Планировка: ["windows", "input", "foo"]'}

        with patch.object(client, "_request", fake_request):
            result = client.plan_categories(
                "сверни окно",
                ["windows", "input", "browser"],
            )
        self.assertEqual(result, ["windows", "input"])

    def test_plan_categories_handles_garbage(self):
        client = LLMClient(use_llm=True, api_key="test")

        def fake_request(payload, api_url=None, api_key=None):
            return {"content": "не JSON"}

        with patch.object(client, "_request", fake_request):
            self.assertIsNone(
                client.plan_categories("тест", ["windows"])
            )


class ListenerThresholdTests(unittest.TestCase):

    def _listener(self):
        return VoiceListener(api_key="test")

    def test_silence_floor_used_when_quiet(self):
        listener = self._listener()
        self.assertAlmostEqual(
            listener.threshold_for(0.0),
            listener.silence_threshold,
        )

    def test_noisy_room_raises_threshold(self):
        listener = self._listener()
        threshold = listener.threshold_for(0.01)
        self.assertGreater(threshold, listener.silence_threshold)

    def test_threshold_capped(self):
        listener = self._listener()
        cap = listener.silence_threshold * listener.noise_max_ratio
        self.assertAlmostEqual(
            listener.threshold_for(10.0),
            cap,
        )

    def test_defaults_for_longer_speech(self):
        listener = self._listener()
        self.assertAlmostEqual(listener.max_speech_seconds, 12.0)
        self.assertAlmostEqual(listener.silence_duration, 0.7)


if __name__ == "__main__":
    unittest.main()