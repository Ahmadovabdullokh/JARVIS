import unittest

from app.commands import handle_command


class FakeMemory:
    def __init__(self):
        self.facts = []

    def remember(self, fact):
        if fact in self.facts:
            return False
        self.facts.append(fact)
        return True

    def set_profile(self, key, value):
        self.facts.append(f"{key}: {value}")
        return True

    def summary(self):
        return "\n".join(self.facts)

    def forget_all(self):
        self.facts.clear()


class CommandTests(unittest.TestCase):

    def test_time_command_addresses_user(self):
        result = handle_command("который час")

        self.assertIn("Сейчас", result)
        self.assertIn("сэр", result)

    def test_date_command(self):
        result = handle_command("какая сегодня дата")

        self.assertIn("Сегодня", result)
        self.assertIn("сэр", result)

    def test_greeting(self):
        self.assertIn(
            "Приветствую",
            handle_command("привет"),
        )

    def test_exit(self):
        self.assertEqual(
            handle_command("отключись"),
            "__EXIT__",
        )

    def test_remember_and_recall(self):
        memory = FakeMemory()

        result = handle_command(
            "запомни, что я предпочитаю тёмную тему",
            memory=memory,
        )

        self.assertIn("Запомнил", result)
        self.assertIn("тёмную тему", memory.summary())

        recall = handle_command(
            "что ты помнишь",
            memory=memory,
        )
        self.assertIn("тёмную тему", recall)

    def test_user_name(self):
        memory = FakeMemory()

        result = handle_command(
            "меня зовут Ахмад",
            memory=memory,
        )

        self.assertIn("Ахмад", result)
        self.assertIn("Имя пользователя: Ахмад", memory.summary())

    def test_forget_all(self):
        memory = FakeMemory()
        memory.remember("факт")

        result = handle_command("очисти память", memory=memory)

        self.assertIn("очищена", result)
        self.assertEqual(memory.summary(), "")


if __name__ == "__main__":
    unittest.main()
