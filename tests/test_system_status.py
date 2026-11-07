import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.pc_agent import PCAgent


class SystemStatusTests(unittest.TestCase):

    def test_system_status_reports_metrics(self):
        memory = SimpleNamespace(
            percent=42.0,
            used=8 * 1024 ** 3,
            total=16 * 1024 ** 3,
        )
        disk = SimpleNamespace(percent=61.0)
        battery = SimpleNamespace(percent=77, power_plugged=True)

        with (
            patch("app.pc_agent.psutil.cpu_percent", return_value=17.0),
            patch("app.pc_agent.psutil.virtual_memory", return_value=memory),
            patch("app.pc_agent.psutil.disk_usage", return_value=disk),
            patch("app.pc_agent.psutil.sensors_battery", return_value=battery),
            patch("app.pc_agent.psutil.boot_time", return_value=0),
            patch("app.pc_agent.time.time", return_value=7200),
        ):
            result = PCAgent().system_status()

        self.assertIn("процессор загружен на 17%", result)
        self.assertIn("память занята на 42%", result)
        self.assertIn("диск занят на 61%", result)
        self.assertIn("заряд батареи 77%", result)
        self.assertIn("2 ч 0 мин", result)

    def test_battery_without_battery(self):
        with patch(
            "app.pc_agent.psutil.sensors_battery",
            return_value=None,
        ):
            result = PCAgent().battery_status()

        self.assertIn("не обнаружена", result)

    def test_system_tools_are_exposed(self):
        names = {
            tool["function"]["name"]
            for tool in PCAgent().get_tools()
        }

        self.assertTrue(
            {
                "system_status",
                "battery_status",
                "list_processes",
                "lock_pc",
                "sleep_pc",
                "shutdown_pc",
                "cancel_shutdown",
            }.issubset(names)
        )

    def test_direct_protocol_commands(self):
        agent = PCAgent()
        agent.minimize_all = lambda: "ok"
        agent.show_desktop = lambda: "ok"
        agent.volume_down = lambda: "ok"

        self.assertIn(
            "Домовой",
            agent.handle("протокол домовой"),
        )
        self.assertIn(
            "Чистый лист",
            agent.handle("протокол чистый лист"),
        )
        self.assertIn(
            "Вечер",
            agent.handle("протокол вечер"),
        )


if __name__ == "__main__":
    unittest.main()
