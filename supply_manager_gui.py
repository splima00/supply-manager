#!/usr/bin/env python3
"""Tk desktop interface for the supply manager."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from supply_manager import (
    DEFAULT_DATABASE,
    add_supply,
    add_vendor,
    connect,
    list_supplies,
    list_vendors,
    remove_supply,
    remove_vendor,
    update_quantity,
    update_supply_vendor,
    verify_user,
)


class SupplyManagerWindow:
    def __init__(self, root: tk.Tk, database: Path) -> None:
        self.root = root
        self.database = database
        self.username: str | None = None
        self.root.title("Supply Manager")
        self.root.geometry("860x560")
        self.root.minsize(680, 420)
        self.show_login()

    def show_login(self) -> None:
        self._clear()
        panel = ttk.Frame(self.root, padding=32)
        panel.pack(expand=True)
        ttk.Label(panel, text="Supply Manager", font=("TkDefaultFont", 20, "bold")).pack(pady=(0, 18))
        ttk.Label(panel, text="Sign in with an account registered in the CLI.").pack(pady=(0, 12))
        self.login_name = tk.StringVar()
        self.login_password = tk.StringVar()
        ttk.Label(panel, text="Username").pack(anchor="w")
        name_entry = ttk.Entry(panel, textvariable=self.login_name, width=34)
        name_entry.pack(pady=(2, 10))
        ttk.Label(panel, text="Password").pack(anchor="w")
        password_entry = ttk.Entry(panel, textvariable=self.login_password, show="*", width=34)
        password_entry.pack(pady=(2, 14))
        password_entry.bind(
            "<Return>", lambda event: self.login() if event.widget == password_entry else None
        )
        ttk.Button(panel, text="Sign in", command=self.login).pack(fill="x")
        name_entry.focus_set()

    def login(self) -> None:
        with connect(self.database) as connection:
            if not verify_user(connection, self.login_name.get().strip(), self.login_password.get()):
                messagebox.showerror("Sign in failed", "Invalid username or password.", parent=self.root)
                return
        self.username = self.login_name.get().strip()
        self.show_inventory()

    def show_inventory(self) -> None:
        self._clear()
        header = ttk.Frame(self.root, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Supply Manager", font=("TkDefaultFont", 18, "bold")).pack(side="left")
        ttk.Label(header, text=f"Signed in as {self.username}").pack(side="right")

        filters = ttk.Frame(self.root, padding=(16, 0, 16, 8))
        filters.pack(fill="x")
        ttk.Label(filters, text="Vendor:").pack(side="left")
        self.vendor_filter = tk.StringVar(value="All vendors")
        self.vendor_box = ttk.Combobox(filters, textvariable=self.vendor_filter, state="readonly", width=24)
        self.vendor_box.pack(side="left", padx=(6, 12))
        self.vendor_box.bind(
            "<<ComboboxSelected>>",
            lambda event: self.refresh() if event.widget == self.vendor_box else None,
        )
        self.low_stock = tk.BooleanVar()
        ttk.Checkbutton(
            filters, text="Low stock only", variable=self.low_stock, command=self.refresh
        ).pack(side="left")
        ttk.Button(filters, text="Refresh", command=self.refresh).pack(side="right")

        columns = ("id", "name", "quantity", "reorder", "vendor")
        self.table = ttk.Treeview(self.root, columns=columns, show="headings", selectmode="browse")
        for column, label, width in (
            ("id", "ID", 55),
            ("name", "Supply", 270),
            ("quantity", "Quantity", 95),
            ("reorder", "Reorder level", 110),
            ("vendor", "Vendor", 200),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w" if column in ("name", "vendor") else "center")
        self.table.pack(fill="both", expand=True, padx=16, pady=8)
        self.table.tag_configure("low", foreground="#b42318")

        actions = ttk.Frame(self.root, padding=(16, 4, 16, 16))
        actions.pack(fill="x")
        for label, callback in (
            ("Add supply", self.add_supply_dialog),
            ("Set quantity", self.update_dialog),
            ("Assign vendor", self.assign_vendor_dialog),
            ("Remove supply", self.remove_selected),
            ("Add vendor", self.add_vendor_dialog),
            ("Remove vendor", self.remove_vendor_dialog),
        ):
            ttk.Button(actions, text=label, command=callback).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Log out", command=self.show_login).pack(side="right")
        self.refresh()

    def refresh(self) -> None:
        if not hasattr(self, "table"):
            return
        with connect(self.database) as connection:
            vendors = list_vendors(connection)
            names = [row["name"] for row in vendors]
            self.vendor_box["values"] = ["All vendors", *names]
            selected_vendor = self.vendor_filter.get()
            if selected_vendor not in self.vendor_box["values"]:
                self.vendor_filter.set("All vendors")
                selected_vendor = "All vendors"
            supplies = list_supplies(
                connection,
                low_stock_only=self.low_stock.get(),
                vendor_name=selected_vendor if selected_vendor != "All vendors" else None,
            )
        self.table.delete(*self.table.get_children())
        for row in supplies:
            tags = ("low",) if row["quantity"] <= row["reorder_level"] else ()
            self.table.insert(
                "",
                "end",
                values=(row["id"], row["name"], row["quantity"], row["reorder_level"], row["vendor"]),
                tags=tags,
            )

    def _selected_name(self) -> str | None:
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("Select a supply", "Choose a supply from the list first.", parent=self.root)
            return None
        return str(self.table.item(selection[0], "values")[1])

    def _run_action(self, action: Callable[[sqlite3.Connection], None]) -> None:
        try:
            with connect(self.database) as connection:
                action(connection)
        except (ValueError, sqlite3.IntegrityError) as error:
            messagebox.showerror("Supply Manager", str(error), parent=self.root)
            return
        self.refresh()

    def add_supply_dialog(self) -> None:
        name = simpledialog.askstring("Add supply", "Supply name:", parent=self.root)
        if name is None:
            return
        quantity = simpledialog.askinteger("Add supply", "Quantity:", minvalue=0, parent=self.root)
        if quantity is None:
            return
        reorder = simpledialog.askinteger(
            "Add supply", "Reorder level:", initialvalue=0, minvalue=0, parent=self.root
        )
        if reorder is None:
            return
        with connect(self.database) as connection:
            vendors = [row["name"] for row in list_vendors(connection)]
        vendor = simpledialog.askstring(
            "Add supply", f"Optional vendor ({', '.join(vendors)}):", parent=self.root
        )
        if vendor is None:
            return
        if not vendor.strip():
            vendor = None
        self._run_action(
            lambda connection: add_supply(
                connection, name.strip(), quantity, reorder, vendor.strip() if vendor else None
            )
        )

    def update_dialog(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        quantity = simpledialog.askinteger("Set quantity", "New quantity:", minvalue=0, parent=self.root)
        if quantity is not None:
            self._run_action(lambda connection: update_quantity(connection, name, quantity))

    def assign_vendor_dialog(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        with connect(self.database) as connection:
            vendors = [row["name"] for row in list_vendors(connection)]
        if not vendors:
            messagebox.showinfo("Assign vendor", "Add a vendor first.", parent=self.root)
            return
        vendor = simpledialog.askstring(
            "Assign vendor", f"Vendor name ({', '.join(vendors)}):", parent=self.root
        )
        if vendor:
            self._run_action(
                lambda connection: update_supply_vendor(connection, name, vendor.strip())
            )

    def remove_selected(self) -> None:
        name = self._selected_name()
        if name and messagebox.askyesno("Remove supply", f"Remove '{name}'?", parent=self.root):
            self._run_action(lambda connection: remove_supply(connection, name))

    def add_vendor_dialog(self) -> None:
        name = simpledialog.askstring("Add vendor", "Vendor name:", parent=self.root)
        if name is None:
            return
        contact = simpledialog.askstring("Add vendor", "Contact details (optional):", parent=self.root)
        if contact is None:
            contact = ""
        self._run_action(lambda connection: add_vendor(connection, name.strip(), contact.strip()))

    def remove_vendor_dialog(self) -> None:
        with connect(self.database) as connection:
            vendors = [row["name"] for row in list_vendors(connection)]
        if not vendors:
            messagebox.showinfo("Remove vendor", "There are no vendors to remove.", parent=self.root)
            return
        name = simpledialog.askstring(
            "Remove vendor", f"Vendor name ({', '.join(vendors)}):", parent=self.root
        )
        if name and messagebox.askyesno("Remove vendor", f"Remove '{name}'?", parent=self.root):
            self._run_action(lambda connection: remove_vendor(connection, name.strip()))

    def _clear(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()


def run(database: Path = DEFAULT_DATABASE) -> int:
    root = tk.Tk()
    SupplyManagerWindow(root, database)
    root.mainloop()
    return 0
