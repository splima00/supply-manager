#!/usr/bin/env python3
"""Dependency-free, loopback-only browser interface for the supply manager."""

from __future__ import annotations

import hmac
import secrets
from html import escape
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIServer, make_server

from supply_manager import (
    DEFAULT_DATABASE,
    add_supply,
    add_vendor,
    connect,
    create_user,
    list_supplies,
    list_vendors,
    remove_supply,
    remove_vendor,
    update_quantity,
    update_supply_vendor,
    verify_user,
)

PAGE_STYLE = """
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#17211d;background:#f3f6f2}
*{box-sizing:border-box}body{margin:0}header{background:#123c32;color:white;padding:22px max(24px,calc((100% - 1120px)/2));display:flex;justify-content:space-between;align-items:center}
h1{font-size:22px;margin:0}main{max-width:1120px;margin:28px auto;padding:0 22px}
.panel{background:white;border:1px solid #e1e8e2;border-radius:14px;padding:20px;margin-bottom:20px;box-shadow:0 5px 18px #173a2510}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}
h2{font-size:17px;margin:0 0 16px}label{display:block;font-size:13px;color:#54635b;margin:10px 0 5px}
input,select,button{font:inherit;border-radius:8px;padding:10px 12px;border:1px solid #d1dbd3}
input,select{width:100%;background:#fff}button,.button{border:0;background:#14765b;color:white;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,.button:hover{background:#0e5c46}.secondary{background:#e9f1eb;color:#1b4939}
form.inline{display:inline}.inline button{padding:7px 10px}.filter{display:flex;gap:10px;align-items:end;max-width:560px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid #e8eee9}
th{font-size:12px;text-transform:uppercase;color:#627169}.low{color:#b42318;font-weight:700}
.flash{padding:12px 14px;border-radius:8px;background:#fff0ec;color:#a12a1b;margin-bottom:16px}
.muted{color:#617168;font-size:14px}.auth{max-width:440px;margin:7vh auto}.auth h2{margin-top:0}
@media(max-width:650px){header{padding:18px}main{margin:16px auto;padding:0 12px}.panel{padding:15px}table{font-size:13px}th,td{padding:8px 5px}.filter{align-items:stretch;flex-direction:column}}
</style>
"""


class SupplyManagerWebApp:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.sessions: dict[str, tuple[str | None, str]] = {}

    def __call__(self, environ: dict, start_response) -> list[bytes]:
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        session_id, username, csrf_token, is_new = self._session(environ)
        try:
            if method == "GET" and path == "/login":
                body = self._login_page(csrf_token, self._query(environ).get("error", [""])[0])
                return self._respond(start_response, "200 OK", body, self._cookie(session_id, is_new))
            if method == "GET" and path == "/":
                if username is None:
                    return self._redirect(start_response, "/login", self._cookie(session_id, is_new))
                body = self._dashboard(username, csrf_token, self._query(environ))
                return self._respond(start_response, "200 OK", body, self._cookie(session_id, is_new))
            if method == "POST":
                fields = self._form(environ)
                supplied_csrf = fields.get("csrf", "").encode("utf-8")
                if not hmac.compare_digest(supplied_csrf, csrf_token.encode("utf-8")):
                    return self._respond(start_response, "403 Forbidden", "<h1>Request expired</h1>")
                return self._post(
                    start_response, path, fields, session_id, username, self._cookie(session_id, is_new)
                )
            return self._respond(start_response, "404 Not Found", "<h1>Not found</h1>")
        except (ValueError, KeyError) as error:
            if username is None:
                body = self._login_page(csrf_token, str(error))
                return self._respond(start_response, "400 Bad Request", body, self._cookie(session_id, is_new))
            return self._redirect(
                start_response, "/?error=" + self._quote(str(error)), self._cookie(session_id, is_new)
            )

    def _session(self, environ: dict) -> tuple[str, str | None, str, bool]:
        cookies = SimpleCookie(environ.get("HTTP_COOKIE", ""))
        cookie = cookies.get("supply_manager_session")
        session_id = cookie.value if cookie else ""
        session = self.sessions.get(session_id)
        if session is not None:
            return session_id, session[0], session[1], False
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        self.sessions[session_id] = (None, csrf_token)
        return session_id, None, csrf_token, True

    def _post(
        self,
        start_response,
        path: str,
        fields: dict[str, str],
        session_id: str,
        username: str | None,
        cookie_header: tuple[str, str] | None,
    ) -> list[bytes]:
        if path == "/login":
            with connect(self.database) as connection:
                if not verify_user(connection, fields.get("username", "").strip(), fields.get("password", "")):
                    return self._redirect(start_response, "/login?error=Invalid%20username%20or%20password", cookie_header)
            self.sessions.pop(session_id, None)
            session_id = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            self.sessions[session_id] = (fields["username"].strip(), csrf_token)
            return self._redirect(start_response, "/", self._cookie(session_id, True))
        if path == "/register":
            with connect(self.database) as connection:
                create_user(connection, fields.get("username", ""), fields.get("password", ""))
            return self._redirect(start_response, "/login?error=Account%20created%3B%20sign%20in")
        if username is None:
            return self._redirect(start_response, "/login")
        if path == "/logout":
            self.sessions.pop(session_id, None)
            return self._redirect(start_response, "/login", ("Set-Cookie", self._expired_cookie()))
        with connect(self.database) as connection:
            if path == "/supplies/add":
                quantity = self._integer(fields, "quantity")
                reorder = self._integer(fields, "reorder_level")
                add_supply(
                    connection,
                    fields.get("name", "").strip(),
                    quantity,
                    reorder,
                    fields.get("vendor", "").strip() or None,
                )
            elif path == "/supplies/update":
                update_quantity(
                    connection,
                    fields.get("name", ""),
                    self._integer(fields, "quantity"),
                )
            elif path == "/supplies/remove":
                remove_supply(connection, fields.get("name", ""))
            elif path == "/supplies/vendor":
                update_supply_vendor(
                    connection, fields.get("name", ""), fields.get("vendor", "")
                )
            elif path == "/vendors/add":
                add_vendor(
                    connection,
                    fields.get("name", "").strip(),
                    fields.get("contact", "").strip(),
                )
            elif path == "/vendors/remove":
                remove_vendor(connection, fields.get("name", ""))
            else:
                return self._respond(start_response, "404 Not Found", "<h1>Not found</h1>")
        return self._redirect(start_response, "/")

    def _dashboard(self, username: str, csrf: str, query: dict[str, list[str]]) -> str:
        low_stock = query.get("low_stock", [""])[0] == "1"
        vendor_filter = query.get("vendor", [""])[0]
        error = query.get("error", [""])[0]
        with connect(self.database) as connection:
            vendors = list_vendors(connection)
            try:
                supplies = list_supplies(
                    connection,
                    low_stock_only=low_stock,
                    vendor_name=vendor_filter or None,
                )
            except ValueError as exc:
                supplies = []
                error = str(exc)
        vendor_options = '<option value="">All vendors</option>' + "".join(
            f'<option value="{escape(row["name"], quote=True)}"'
            f'{" selected" if row["name"] == vendor_filter else ""}>'
            f'{escape(row["name"])}</option>'
            for row in vendors
        )
        rows = "".join(
            self._supply_row(row, csrf) for row in supplies
        ) or '<tr><td colspan="5" class="muted">No supplies match this filter.</td></tr>'
        vendor_names = "".join(
            f'<option value="{escape(row["name"], quote=True)}">{escape(row["name"])}</option>'
            for row in vendors
        )
        error_panel = f'<div class="flash">{escape(error)}</div>' if error else ""
        csrf_field = f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Supply Manager</title>{PAGE_STYLE}
<header><h1>Supply Manager</h1><form method="post" action="/logout">{csrf_field}
<span>Signed in as {escape(username)}</span> <button class="secondary">Log out</button></form></header>
<main>{error_panel}
<section class="panel"><h2>Inventory</h2><form class="filter" method="get" action="/">
<label>Vendor<select name="vendor">{vendor_options}</select></label>
<label><input style="width:auto" type="checkbox" name="low_stock" value="1" {"checked" if low_stock else ""}> Low stock only</label>
<button>Filter</button></form><div style="overflow-x:auto;margin-top:16px"><table><thead><tr>
<th>Supply</th><th>Quantity</th><th>Reorder at</th><th>Vendor</th><th>Actions</th>
</tr></thead><tbody>{rows}</tbody></table></div></section>
<div class="grid">
<section class="panel"><h2>Add supply</h2><form method="post" action="/supplies/add">{csrf_field}
<label>Name<input name="name" required></label><label>Quantity<input name="quantity" type="number" min="0" value="0" required></label>
<label>Reorder level<input name="reorder_level" type="number" min="0" value="0" required></label>
<label>Vendor<select name="vendor">{vendor_options}</select></label><button>Add supply</button></form></section>
<section class="panel"><h2>Add vendor</h2><form method="post" action="/vendors/add">{csrf_field}
<label>Name<input name="name" required></label><label>Contact<input name="contact"></label>
<button>Add vendor</button></form><h2 style="margin-top:24px">Remove vendor</h2>
<form method="post" action="/vendors/remove">{csrf_field}<label>Vendor<select name="name" required>
{vendor_names}</select></label><button class="secondary">Remove vendor</button></form></section>
</div></main></html>"""

    @staticmethod
    def _supply_row(row, csrf: str) -> str:
        name = escape(row["name"], quote=True)
        vendor = escape(row["vendor"], quote=True)
        low = row["quantity"] <= row["reorder_level"]
        token = escape(csrf, quote=True)
        return f"""<tr><td>{escape(row["name"])}</td><td class="{"low" if low else ""}">{row["quantity"]}</td>
<td>{row["reorder_level"]}</td><td>{escape(row["vendor"])}</td><td>
<form class="inline" method="post" action="/supplies/update">{SupplyManagerWebApp._csrf(token)}
<input type="hidden" name="name" value="{name}"><input aria-label="New quantity for {name}" name="quantity" type="number" min="0" value="{row["quantity"]}" required style="width:90px">
<button class="secondary">Set</button></form>
<form class="inline" method="post" action="/supplies/remove" onsubmit="return confirm('Remove this supply?')">
{SupplyManagerWebApp._csrf(token)}<input type="hidden" name="name" value="{name}"><button class="secondary">Remove</button></form>
<form class="inline" method="post" action="/supplies/vendor">{SupplyManagerWebApp._csrf(token)}
<input type="hidden" name="name" value="{name}"><input name="vendor" aria-label="Vendor for {name}" placeholder="Vendor name" required style="width:120px">
<button class="secondary">Assign</button></form></td></tr>"""

    @staticmethod
    def _csrf(token: str) -> str:
        return f'<input type="hidden" name="csrf" value="{token}">'

    @staticmethod
    def _login_page(csrf: str, error: str) -> str:
        csrf_field = f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        alert = f'<div class="flash">{escape(error)}</div>' if error else ""
        return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in · Supply Manager</title>{PAGE_STYLE}
<main class="auth"><section class="panel"><h1>Supply Manager</h1><p class="muted">Sign in to manage your inventory.</p>{alert}
<form method="post" action="/login">{csrf_field}<label>Username<input name="username" autocomplete="username" required></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
<button style="width:100%;margin-top:14px">Sign in</button></form></section>
<section class="panel"><h2>Create account</h2><form method="post" action="/register">{csrf_field}
<label>Username<input name="username" autocomplete="username" required></label>
<label>Password<input name="password" type="password" autocomplete="new-password" required></label>
<button class="secondary">Register</button></form></section></main></html>"""

    @staticmethod
    def _form(environ: dict) -> dict[str, str]:
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError as error:
            raise ValueError("Invalid request body length") from error
        if length < 0 or length > 65536:
            raise ValueError("Request body is too large")
        try:
            body = environ["wsgi.input"].read(length).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Form data must be UTF-8") from error
        values = parse_qs(body, keep_blank_values=True)
        return {key: value[0] for key, value in values.items()}

    @staticmethod
    def _integer(fields: dict[str, str], key: str) -> int:
        try:
            value = int(fields.get(key, ""))
        except ValueError as error:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} must be a whole number") from error
        if value < 0:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} cannot be negative")
        return value

    @staticmethod
    def _query(environ: dict) -> dict[str, list[str]]:
        return parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)

    @staticmethod
    def _quote(value: str) -> str:
        from urllib.parse import quote

        return quote(value, safe="")

    @staticmethod
    def _cookie(session_id: str, new: bool) -> tuple[str, str] | None:
        if not new:
            return None
        return (
            "Set-Cookie",
            f"supply_manager_session={session_id}; HttpOnly; SameSite=Strict; Path=/",
        )

    @staticmethod
    def _expired_cookie() -> str:
        return "supply_manager_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"

    @staticmethod
    def _respond(
        start_response,
        status: str,
        body: str,
        cookie: tuple[str, str] | None = None,
    ) -> list[bytes]:
        data = body.encode("utf-8")
        headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(data)))]
        if cookie:
            headers.append(cookie)
        start_response(status, headers)
        return [data]

    @staticmethod
    def _redirect(start_response, location: str, cookie: tuple[str, str] | None = None) -> list[bytes]:
        headers = [("Location", location), ("Content-Length", "0")]
        if cookie:
            headers.append(cookie)
        start_response("303 See Other", headers)
        return [b""]


def run(database: Path = DEFAULT_DATABASE, port: int = 8000) -> int:
    try:
        server: WSGIServer = make_server("127.0.0.1", port, SupplyManagerWebApp(database))
    except OSError as error:
        raise RuntimeError(f"Could not start the local web app on port {port}: {error}") from error
    print(f"Supply Manager web app: http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb app stopped.")
    finally:
        server.server_close()
    return 0
