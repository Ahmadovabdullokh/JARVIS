"""Вопросы о кадре камеры распознаются и получают инструмент зрения."""

import unittest

from app.pc_agent import PCAgent, is_camera_question


class CameraQuestionDetectionTests(unittest.TestCase):

    def test_show_and_tell_phrases_are_camera_questions(self):
        for phrase in (
            "что ты видишь",
            "что видно",
            "ты видишь меня",
            "что я держу в руках",
            "что я держу на руках",
            "что у меня в руке",
            "что у меня на столе",
            "что это за предмет",
            "опиши кадр",
            "посмотри на меня",
            "что на камере",
            "узнаёшь меня",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(is_camera_question(phrase))

    def test_screen_and_unrelated_phrases_are_not_camera_questions(self):
        for phrase in (
            "что на экране",
            "что видно на мониторе",
            "сделай скриншот",
            "что это",
            "открой камеру",
            "включи камеру",
            "исправь ошибку в проекте",
            "который час",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(is_camera_question(phrase))

    def test_code_mode_offers_camera_tool_for_show_and_tell(self):
        agent = PCAgent()

        names = [
            tool["function"]["name"]
            for tool in agent.get_code_llm_tools(
                "что я держу в руках"
            )
        ]

        self.assertIn("look_at_camera", names)

    def test_code_mode_keeps_camera_tool_out_of_regular_tasks(self):
        agent = PCAgent()

        names = [
            tool["function"]["name"]
            for tool in agent.get_code_llm_tools(
                "исправь баг в проекте"
            )
        ]

        self.assertNotIn("look_at_camera", names)


if __name__ == "__main__":
    unittest.main()
