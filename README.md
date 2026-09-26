# Supply Manager

A small command-line supply manager backed by SQLite. It uses only the Python standard library.

## Run

From this directory:

```bash
python3 supply_manager.py register alice
python3 supply_manager.py login alice
python3 supply_manager.py --user alice add "Printer paper" 25 --reorder-level 10
python3 supply_manager.py --user alice vendor-add "Office Depot" --contact purchasing@example.com
python3 supply_manager.py --user alice add "Coffee" 4 --reorder-level 5 --vendor "Office Depot"
python3 supply_manager.py --user alice list
python3 supply_manager.py --user alice list --low-stock
python3 supply_manager.py --user alice list --vendor "Office Depot"
python3 supply_manager.py --user alice update Coffee 12
python3 supply_manager.py --user alice vendor-update Coffee "Office Depot"
python3 supply_manager.py --user alice remove "Printer paper"
python3 supply_manager.py --user alice vendor-list
python3 supply_manager.py --user alice vendor-remove "Office Depot"
```

The database is created automatically as `supplies.db`. Use `--database path/to/file.db` to select another database.
Registration and login prompt for passwords without displaying them. Each supply or vendor command also prompts for the selected user's password. Passwords are stored as salted PBKDF2 hashes.

## Commands

- `register USERNAME`
- `login USERNAME`
- `add NAME QUANTITY [--reorder-level LEVEL]`
- `vendor-add NAME [--contact CONTACT]`
- `vendor-list`
- `vendor-remove NAME`
- `vendor-update SUPPLY VENDOR`
- `list [--low-stock] [--vendor VENDOR]`
- `update NAME QUANTITY`
- `remove NAME`

All commands except `register` and `login` require the global `--user USERNAME` option.
