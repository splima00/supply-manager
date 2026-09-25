# Supply Manager

A small command-line supply manager backed by SQLite. It uses only the Python standard library.

## Run

From this directory:

```bash
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
```

The database is created automatically as `supplies.db`. Use `--database path/to/file.db` to select another database.

## Commands

- `add NAME QUANTITY [--reorder-level LEVEL]`
- `vendor-add NAME [--contact CONTACT]`
- `vendor-list`
- `vendor-remove NAME`
- `vendor-update SUPPLY VENDOR`
- `list [--low-stock] [--vendor VENDOR]`
- `update NAME QUANTITY`
- `remove NAME`
