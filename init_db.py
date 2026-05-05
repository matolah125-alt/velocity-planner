import sqlite3
import os

def initialize():
    # Ensure we use the same path logic as helpers.py
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'database.db')
    
    connection = sqlite3.connect(db_path)
    
    # Read the SQL instructions from your schema.sql file
    schema_path = os.path.join(base_dir, 'schema.sql')
    with open(schema_path) as f:
        connection.executescript(f.read())

    connection.commit()
    connection.close()
    print("Database initialized successfully!")

if __name__ == "__main__":
    initialize()