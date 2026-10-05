"""Focused tests for the command-line application's interactive startup."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import supply_manager


class SupplyManagerCliTests(unittest.TestCase):
    def test_no_command_logs_in_before_opening_menu(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "test.db"
            with supply_manager.connect(database) as connection:
                supply_manager.create_user(connection, "tester", "secret")

            def assert_logged_in_before_menu(connection, menu_database) -> None:
                self.assertEqual(menu_database, database)
                self.assertEqual(
                    supply_manager.current_session(connection, database),
                    "tester",
                )

            with (
                patch(
                    "sys.argv",
                    ["supply_manager.py", "--database", str(database)],
                ),
                patch("builtins.input", return_value="tester") as prompt_username,
                patch("supply_manager.getpass.getpass", return_value="secret") as prompt_password,
                patch(
                    "supply_manager.run_menu",
                    side_effect=assert_logged_in_before_menu,
                ) as run_menu,
            ):
                self.assertEqual(supply_manager.main(), 0)

            prompt_username.assert_called_once_with("Username: ")
            prompt_password.assert_called_once_with("Password: ")
            run_menu.assert_called_once()


if __name__ == "__main__":
    unittest.main()
