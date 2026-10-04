"""Focused tests for the browser application's authentication and inventory flow."""

from __future__ import annotations

import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

from supply_manager import connect, create_user
from supply_manager_web import SupplyManagerWebApp


class SupplyManagerWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        with connect(self.database) as connection:
            create_user(connection, "tester", "secret")
        self.app = SupplyManagerWebApp(self.database)
        self.cookie = ""

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        form: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str], str]:
        body = urlencode(form or {}).encode()
        status_headers: dict[str, str] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            status_headers["status"] = status
            status_headers.update(headers)

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": BytesIO(body),
            "HTTP_COOKIE": self.cookie,
        }
        response = b"".join(self.app(environ, start_response)).decode()
        set_cookie = status_headers.get("Set-Cookie", "")
        if set_cookie:
            self.cookie = set_cookie.split(";", 1)[0]
        return status_headers["status"], status_headers, response

    def csrf(self, html: str) -> str:
        match = re.search(r'name="csrf" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1)  # type: ignore[union-attr]

    def sign_in(self) -> str:
        _, _, login_page = self.request("GET", "/login")
        token = self.csrf(login_page)
        status, _, _ = self.request(
            "POST", "/login", {"csrf": token, "username": "tester", "password": "secret"}
        )
        self.assertEqual(status, "303 See Other")
        _, _, dashboard = self.request("GET", "/")
        return self.csrf(dashboard)

    def test_login_and_add_supply(self) -> None:
        csrf = self.sign_in()
        status, _, _ = self.request(
            "POST",
            "/supplies/add",
            {
                "csrf": csrf,
                "name": "Printer paper",
                "quantity": "8",
                "reorder_level": "10",
                "vendor": "",
            },
        )
        self.assertEqual(status, "303 See Other")
        _, _, dashboard = self.request("GET", "/")
        self.assertIn("Printer paper", dashboard)
        self.assertIn('class="low"', dashboard)

    def test_inventory_mutation_requires_csrf(self) -> None:
        self.sign_in()
        status, _, _ = self.request(
            "POST",
            "/supplies/add",
            {"csrf": "incorrect", "name": "Do not add", "quantity": "1", "reorder_level": "0"},
        )
        self.assertEqual(status, "403 Forbidden")
        _, _, dashboard = self.request("GET", "/")
        self.assertNotIn("Do not add", dashboard)

    def test_login_rejects_invalid_credentials(self) -> None:
        _, _, login_page = self.request("GET", "/login")
        status, headers, _ = self.request(
            "POST",
            "/login",
            {"csrf": self.csrf(login_page), "username": "tester", "password": "wrong"},
        )
        self.assertEqual(status, "303 See Other")
        self.assertEqual(headers["Location"], "/login?error=Invalid%20username%20or%20password")

    def test_browser_registration_creates_sign_in_account(self) -> None:
        _, _, login_page = self.request("GET", "/login")
        status, _, _ = self.request(
            "POST",
            "/register",
            {"csrf": self.csrf(login_page), "username": "new-user", "password": "new-secret"},
        )
        self.assertEqual(status, "303 See Other")
        _, _, refreshed_login = self.request("GET", "/login")
        status, _, _ = self.request(
            "POST",
            "/login",
            {
                "csrf": self.csrf(refreshed_login),
                "username": "new-user",
                "password": "new-secret",
            },
        )
        self.assertEqual(status, "303 See Other")

    def test_vendor_and_supply_content_is_html_escaped(self) -> None:
        csrf = self.sign_in()
        self.request(
            "POST",
            "/vendors/add",
            {"csrf": csrf, "name": "Parts & Co", "contact": ""},
        )
        self.request(
            "POST",
            "/supplies/add",
            {
                "csrf": csrf,
                "name": "<Ink>",
                "quantity": "4",
                "reorder_level": "1",
                "vendor": "Parts & Co",
            },
        )
        _, _, dashboard = self.request("GET", "/")
        self.assertIn("&lt;Ink&gt;", dashboard)
        self.assertIn("Parts &amp; Co", dashboard)
        self.assertNotIn("<Ink>", dashboard)

    def test_non_ascii_invalid_csrf_is_rejected(self) -> None:
        self.sign_in()
        status, _, _ = self.request(
            "POST",
            "/supplies/add",
            {"csrf": "invalid–token", "name": "Nope", "quantity": "1", "reorder_level": "0"},
        )
        self.assertEqual(status, "403 Forbidden")


if __name__ == "__main__":
    unittest.main()
