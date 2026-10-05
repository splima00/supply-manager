#!/usr/bin/env python3
"""Small command-line supply manager backed by SQLite."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from pathlib import Path

DEFAULT_DATABASE = Path(__file__).with_name("supplies.db")
PASSWORD_ITERATIONS = 310_000


def connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            contact TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS supplies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            quantity INTEGER NOT NULL CHECK (quantity >= 0),
            reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
            vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            salt BLOB NOT NULL,
            password_hash BLOB NOT NULL,
            iterations INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            username TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
            token_hash TEXT NOT NULL
        )
        """
    )
    supply_columns = {row[1] for row in connection.execute("PRAGMA table_info(supplies)")}
    if "vendor_id" not in supply_columns:
        connection.execute("ALTER TABLE supplies ADD COLUMN vendor_id INTEGER REFERENCES vendors(id)")
    connection.commit()
    return connection


def create_user(connection: sqlite3.Connection, username: str, password: str) -> None:
    if not username.strip():
        raise ValueError("Username cannot be empty")
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    try:
        connection.execute(
            "INSERT INTO users (username, salt, password_hash, iterations) VALUES (?, ?, ?, ?)",
            (username, salt, password_hash, PASSWORD_ITERATIONS),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        raise ValueError(f"User '{username}' already exists") from error


def verify_user(connection: sqlite3.Connection, username: str, password: str) -> bool:
    user = connection.execute(
        "SELECT salt, password_hash, iterations FROM users WHERE username = ?", (username,)
    ).fetchone()
    if user is None:
        return False
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), user["salt"], user["iterations"]
    )
    return hmac.compare_digest(password_hash, user["password_hash"])


def session_file(database: Path) -> Path:
    return database.with_name(database.name + ".session")


def login(
    connection: sqlite3.Connection,
    database: Path,
    username: str | None = None,
) -> str:
    print("Log in to Supply Manager")
    if username is None:
        username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    if not verify_user(connection, username, password):
        raise ValueError("Invalid username or password")
    save_session(connection, database, username)
    print(f"Logged in as '{username}'.")
    return username


def save_session(connection: sqlite3.Connection, database: Path, username: str) -> None:
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    connection.execute(
        "INSERT OR REPLACE INTO auth_sessions (username, token_hash) VALUES (?, ?)",
        (username, token_hash),
    )
    connection.commit()
    path = session_file(database)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as session_file_handle:
        json.dump({"username": username, "token": token}, session_file_handle)


def current_session(connection: sqlite3.Connection, database: Path) -> str | None:
    path = session_file(database)
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
        username = session["username"]
        token = session["token"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(username, str) or not isinstance(token, str):
        return None
    row = connection.execute(
        "SELECT token_hash FROM auth_sessions WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        return None
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    return username if hmac.compare_digest(token_hash, row["token_hash"]) else None


def clear_session(connection: sqlite3.Connection, database: Path) -> None:
    path = session_file(database)
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
        username = session.get("username")
        token = session.get("token")
        if isinstance(username, str) and isinstance(token, str):
            token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
            connection.execute(
                "DELETE FROM auth_sessions WHERE username = ? AND token_hash = ?",
                (username, token_hash),
            )
            connection.commit()
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    path.unlink(missing_ok=True)


def find_vendor_id(connection: sqlite3.Connection, name: str) -> int:
    vendor = connection.execute("SELECT id FROM vendors WHERE name = ?", (name,)).fetchone()
    if vendor is None:
        raise ValueError(f"No vendor named '{name}' was found")
    return vendor["id"]


def add_vendor(connection: sqlite3.Connection, name: str, contact: str) -> None:
    try:
        connection.execute("INSERT INTO vendors (name, contact) VALUES (?, ?)", (name, contact))
        connection.commit()
    except sqlite3.IntegrityError as error:
        raise ValueError(f"A vendor named '{name}' already exists") from error


def list_vendors(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(connection.execute("SELECT id, name, contact FROM vendors ORDER BY name COLLATE NOCASE"))


def remove_vendor(connection: sqlite3.Connection, name: str) -> None:
    result = connection.execute("DELETE FROM vendors WHERE name = ?", (name,))
    if result.rowcount == 0:
        raise ValueError(f"No vendor named '{name}' was found")
    connection.commit()


def add_supply(
    connection: sqlite3.Connection,
    name: str,
    quantity: int,
    reorder_level: int,
    vendor_name: str | None = None,
) -> None:
    try:
        vendor_id = find_vendor_id(connection, vendor_name) if vendor_name else None
        connection.execute(
            "INSERT INTO supplies (name, quantity, reorder_level, vendor_id) VALUES (?, ?, ?, ?)",
            (name, quantity, reorder_level, vendor_id),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        raise ValueError(f"A supply named '{name}' already exists") from error


def list_supplies(
    connection: sqlite3.Connection,
    low_stock_only: bool = False,
    vendor_name: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT supplies.id, supplies.name, supplies.quantity, supplies.reorder_level,
               COALESCE(vendors.name, '-') AS vendor
        FROM supplies
        LEFT JOIN vendors ON vendors.id = supplies.vendor_id
    """
    conditions: list[str] = []
    parameters: list[int] = []
    if low_stock_only:
        conditions.append("supplies.quantity <= supplies.reorder_level")
    if vendor_name:
        parameters.append(find_vendor_id(connection, vendor_name))
        conditions.append("supplies.vendor_id = ?")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY supplies.name COLLATE NOCASE"
    return list(connection.execute(query, parameters))


def update_quantity(connection: sqlite3.Connection, name: str, quantity: int) -> None:
    result = connection.execute("UPDATE supplies SET quantity = ? WHERE name = ?", (quantity, name))
    if result.rowcount == 0:
        raise ValueError(f"No supply named '{name}' was found")
    connection.commit()


def update_supply_vendor(connection: sqlite3.Connection, supply_name: str, vendor_name: str) -> None:
    vendor_id = find_vendor_id(connection, vendor_name)
    result = connection.execute(
        "UPDATE supplies SET vendor_id = ? WHERE name = ?",
        (vendor_id, supply_name),
    )
    if result.rowcount == 0:
        raise ValueError(f"No supply named '{supply_name}' was found")
    connection.commit()


def remove_supply(connection: sqlite3.Connection, name: str) -> None:
    result = connection.execute("DELETE FROM supplies WHERE name = ?", (name,))
    if result.rowcount == 0:
        raise ValueError(f"No supply named '{name}' was found")
    connection.commit()


def print_supplies(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("No supplies found.")
        return
    print(f"{'ID':>3}  {'NAME':<30} {'QTY':>5} {'REORDER':>7}  VENDOR")
    print("---  " + "-" * 30 + " " + "----- " + "-------  " + "-" * 20)
    for row in rows:
        print(
            f"{row['id']:>3}  {row['name']:<30} {row['quantity']:>5} "
            f"{row['reorder_level']:>7}  {row['vendor']}"
        )


def print_vendors(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("No vendors found.")
        return
    print(f"{'ID':>3}  {'NAME':<30} CONTACT")
    print("---  " + "-" * 30 + " " + "-" * 30)
    for row in rows:
        print(f"{row['id']:>3}  {row['name']:<30} {row['contact']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage household or business supplies.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="SQLite database path")
    parser.add_argument("--user", help="Authenticate as this user")
    commands = parser.add_subparsers(dest="command")

    register = commands.add_parser("register", help="Create a user account")
    register.add_argument("username")

    login = commands.add_parser("login", help="Verify a user password")
    login.add_argument("username")

    commands.add_parser("logout", help="End the persistent login session")
    commands.add_parser("menu", help="Open the interactive action menu")
    commands.add_parser("desktop", help="Open the desktop graphical interface")
    web = commands.add_parser("web", help="Start the local browser application")
    web.add_argument("--port", type=int, default=8000, help="Local web server port (default: 8000)")

    add = commands.add_parser("add", help="Add a supply")
    add.add_argument("name")
    add.add_argument("quantity", type=int)
    add.add_argument("--reorder-level", type=int, default=0)
    add.add_argument("--vendor", help="Vendor name")

    vendor_add = commands.add_parser("vendor-add", help="Add a vendor")
    vendor_add.add_argument("name")
    vendor_add.add_argument("--contact", default="", help="Email, phone number, or other contact detail")

    commands.add_parser("vendor-list", help="List vendors")

    vendor_remove = commands.add_parser("vendor-remove", help="Remove a vendor")
    vendor_remove.add_argument("name")

    show = commands.add_parser("list", aliases=["show"], help="List supplies")
    show.add_argument("--low-stock", action="store_true", help="Show supplies at or below reorder level")
    show.add_argument("--vendor", help="Show supplies from this vendor")

    update = commands.add_parser("update", help="Set a supply quantity")
    update.add_argument("name")
    update.add_argument("quantity", type=int)

    vendor_update = commands.add_parser("vendor-update", help="Assign a supply to a vendor")
    vendor_update.add_argument("supply")
    vendor_update.add_argument("vendor")

    remove = commands.add_parser("remove", help="Remove a supply")
    remove.add_argument("name")
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if arguments.command is None:
        arguments.command = "menu"
    if arguments.command == "desktop":
        from supply_manager_gui import run as run_desktop

        return run_desktop(arguments.database)
    if arguments.command == "web":
        if not 1 <= arguments.port <= 65535:
            parser.error("port must be between 1 and 65535")
        from supply_manager_web import run as run_web

        return run_web(arguments.database, arguments.port)
    if arguments.command in {"add", "update"} and arguments.quantity < 0:
        parser.error("quantity cannot be negative")
    if arguments.command == "add" and arguments.reorder_level < 0:
        parser.error("reorder level cannot be negative")
    try:
        with connect(arguments.database) as connection:
            if arguments.command == "register":
                password = getpass.getpass("New password: ")
                confirmation = getpass.getpass("Confirm password: ")
                if password != confirmation:
                    raise ValueError("Passwords do not match")
                create_user(connection, arguments.username, password)
                print(f"Registered user '{arguments.username}'.")
            elif arguments.command == "login":
                login(connection, arguments.database, arguments.username)
            elif arguments.command == "logout":
                clear_session(connection, arguments.database)
                print("Logged out.")
            else:
                username = arguments.user or current_session(connection, arguments.database)
                if arguments.command == "menu" and username is None:
                    login(connection, arguments.database)
                elif arguments.user:
                    password = getpass.getpass("Password: ")
                    if not verify_user(connection, username, password):
                        raise ValueError("Invalid username or password")
                elif username is None:
                    raise ValueError("Log in first with 'login USERNAME' or use --user USERNAME")

                if arguments.command == "menu":
                    run_menu(connection, arguments.database)
                    return 0

            if arguments.command == "add":
                add_supply(
                    connection,
                    arguments.name,
                    arguments.quantity,
                    arguments.reorder_level,
                    arguments.vendor,
                )
                print(f"Added '{arguments.name}'.")
            elif arguments.command in {"list", "show"}:
                print_supplies(list_supplies(connection, arguments.low_stock, arguments.vendor))
            elif arguments.command == "update":
                update_quantity(connection, arguments.name, arguments.quantity)
                print(f"Updated '{arguments.name}'.")
            elif arguments.command == "vendor-update":
                update_supply_vendor(connection, arguments.supply, arguments.vendor)
                print(f"Updated vendor for '{arguments.supply}'.")
            elif arguments.command == "remove":
                remove_supply(connection, arguments.name)
                print(f"Removed '{arguments.name}'.")
            elif arguments.command == "vendor-add":
                add_vendor(connection, arguments.name, arguments.contact)
                print(f"Added vendor '{arguments.name}'.")
            elif arguments.command == "vendor-list":
                print_vendors(list_vendors(connection))
            elif arguments.command == "vendor-remove":
                remove_vendor(connection, arguments.name)
                print(f"Removed vendor '{arguments.name}'.")
    except ValueError as error:
        parser.error(str(error))
    return 0


def run_menu(connection: sqlite3.Connection, database: Path) -> None:
    actions = {
        "1": "List supplies",
        "2": "Add supply",
        "3": "Update supply quantity",
        "4": "Remove supply",
        "5": "List vendors",
        "6": "Add vendor",
        "7": "Assign vendor to supply",
        "8": "Remove vendor",
        "9": "Log out",
        "0": "Exit",
    }
    while True:
        print("Supply Manager")
        for key, label in actions.items():
            print(f"{key}. {label}")
        choice = input("Choose an action: ").strip()
        try:
            if choice == "0":
                return
            if choice == "9":
                clear_session(connection, database)
                print("Logged out.")
                return
            if choice == "1":
                print_supplies(list_supplies(connection,low_stock_only=input("Show low stock only? (y/n) [n]: ").strip().lower() == "y", vendor_name=input("Filter by vendor (leave blank for all): ").strip() or None))
            elif choice == "2":
                name = input("Supply name: ").strip()
                quantity = int(input("Quantity: "))
                reorder_level = int(input("Reorder level [0]: ") or "0")
                vendor = input("Vendor name [optional]: ").strip() or None
                if quantity < 0 or reorder_level < 0:
                    raise ValueError("Quantity and reorder level cannot be negative")
                add_supply(connection, name, quantity, reorder_level, vendor)
                print(f"Added '{name}'.")
            elif choice == "3":
                name = input("Supply name: ").strip()
                quantity = int(input("New quantity: "))
                if quantity < 0:
                    raise ValueError("Quantity cannot be negative")
                update_quantity(connection, name, quantity)
                print(f"Updated '{name}'.")
            elif choice == "4":
                name = input("Supply name: ").strip()
                remove_supply(connection, name)
                print(f"Removed '{name}'.")
            elif choice == "5":
                print_vendors(list_vendors(connection))
            elif choice == "6":
                name = input("Vendor name: ").strip()
                contact = input("Contact [optional]: ").strip()
                add_vendor(connection, name, contact)
                print(f"Added vendor '{name}'.")
            elif choice == "7":
                supply = input("Supply name: ").strip()
                vendor = input("Vendor name: ").strip()
                update_supply_vendor(connection, supply, vendor)
                print(f"Updated vendor for '{supply}'.")
            elif choice == "8":
                name = input("Vendor name: ").strip()
                remove_vendor(connection, name)
                print(f"Removed vendor '{name}'.")
            else:
                print("Choose one of the listed actions.")
        except (ValueError, sqlite3.IntegrityError) as error:
            print(f"Error: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
