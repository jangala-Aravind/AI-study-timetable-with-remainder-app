"""
One-time migration: add remind_at and notified columns to reminder_note table.

Run this ONCE from your project root (with your venv active):
    python migrate_add_remind_at.py

It is safe to run multiple times — it skips columns that already exist.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'timetable.db')

# Fallback: some setups place the db directly in the project root
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(__file__), 'timetable.db')

if not os.path.exists(DB_PATH):
    print(f"ERROR: Could not find timetable.db. Tried:\n"
          f"  instance/timetable.db\n"
          f"  timetable.db\n"
          f"Set DB_PATH manually at the top of this script.")
    exit(1)

print(f"Using database: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

# Check which columns already exist
cur.execute("PRAGMA table_info(reminder_note)")
existing_columns = {row[1] for row in cur.fetchall()}
print(f"Existing columns: {existing_columns}")

migrations = [
    ("remind_at", "ALTER TABLE reminder_note ADD COLUMN remind_at DATETIME"),
    ("notified",  "ALTER TABLE reminder_note ADD COLUMN notified  BOOLEAN NOT NULL DEFAULT 0"),
]

for col_name, sql in migrations:
    if col_name in existing_columns:
        print(f"  SKIP  '{col_name}' already exists.")
    else:
        cur.execute(sql)
        print(f"  ADDED '{col_name}'")

conn.commit()
conn.close()
print("\nMigration complete. Restart your Flask app.")
