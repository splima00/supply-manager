# Supply Manager

A small command-line supply manager backed by SQLite. It uses only the Python standard library.

## Run

From this directory:

```bash
python3 supply_manager.py register alice
python3 supply_manager.py login alice
python3 supply_manager.py menu
python3 supply_manager.py add "Printer paper" 25 --reorder-level 10
python3 supply_manager.py vendor-add "Office Depot" --contact purchasing@example.com
python3 supply_manager.py add "Coffee" 4 --reorder-level 5 --vendor "Office Depot"
python3 supply_manager.py list
python3 supply_manager.py list --low-stock
python3 supply_manager.py list --vendor "Office Depot"
python3 supply_manager.py update Coffee 12
python3 supply_manager.py vendor-update Coffee "Office Depot"
python3 supply_manager.py remove "Printer paper"
python3 supply_manager.py vendor-list
python3 supply_manager.py vendor-remove "Office Depot"
python3 supply_manager.py logout
```

The database is created automatically as `supplies.db`. Use `--database path/to/file.db` to select another database.
Registration and login prompt for passwords without displaying them. Login persists a local session, so later commands and the interactive menu do not prompt again. `logout` ends the session. The session token is stored with owner-only file permissions; SQLite stores only its hash. Passwords are stored as salted PBKDF2 hashes. For one-off commands, `--user USERNAME` remains available and prompts for that user's password.

## Commands

- `register USERNAME`
- `login USERNAME`
- `logout`
- `menu`
- `add NAME QUANTITY [--reorder-level LEVEL]`
- `vendor-add NAME [--contact CONTACT]`
- `vendor-list`
- `vendor-remove NAME`
- `vendor-update SUPPLY VENDOR`
- `list [--low-stock] [--vendor VENDOR]`
- `update NAME QUANTITY`
- `remove NAME`

Supply and vendor commands use the persistent login by default. Pass `--user USERNAME` to authenticate for a single command instead.
