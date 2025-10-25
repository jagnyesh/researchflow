"""
Migration Script: Add missing columns to escalations table

This script adds columns that were added to the Escalation model but don't exist
in the database yet:
- escalation_reason
- severity
- recommended_action
- auto_resolved
- resolution_agent
"""

import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def migrate_escalations_table():
    """Add missing columns to escalations table"""
    db_path = 'dev.db'

    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check current columns
    cursor.execute("PRAGMA table_info(escalations)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    print(f"Existing columns: {existing_columns}\n")

    # Columns to add with their SQL definitions
    new_columns = {
        'escalation_reason': 'VARCHAR',
        'severity': 'VARCHAR DEFAULT "medium"',
        'recommended_action': 'TEXT',
        'auto_resolved': 'BOOLEAN DEFAULT 0',
        'resolution_agent': 'VARCHAR'
    }

    # Add missing columns
    added = []
    skipped = []

    for column_name, column_def in new_columns.items():
        if column_name not in existing_columns:
            try:
                sql = f"ALTER TABLE escalations ADD COLUMN {column_name} {column_def}"
                print(f"Adding column: {column_name}")
                cursor.execute(sql)
                added.append(column_name)
            except Exception as e:
                print(f"❌ Error adding {column_name}: {e}")
                return False
        else:
            skipped.append(column_name)

    conn.commit()
    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Added columns: {len(added)}")
    for col in added:
        print(f"  ✓ {col}")

    if skipped:
        print(f"\nSkipped (already exist): {len(skipped)}")
        for col in skipped:
            print(f"  - {col}")

    print("\n✓ Escalations table migrated successfully")
    return True


if __name__ == "__main__":
    migrate_escalations_table()
