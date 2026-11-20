
import sqlite3
from pathlib import Path

folder = Path(__file__).parent / "database"

for filename in ["inventory.db", "inventory_backup.db"]:
    path = folder / filename

    print(f"\nChecking: {filename}")

    if not path.exists():
        print("File not found!")
        continue

    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro",
            uri=True
        )

        result = connection.execute(
            "PRAGMA integrity_check"
        ).fetchall()

        print("Integrity check:", result)

        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

        print("Tables:", tables)

        connection.close()

    except sqlite3.DatabaseError as error:
        print("Database error:", error)
