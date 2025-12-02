import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "users.db")

def add_credits(email, amount):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if user exists
    cursor.execute("SELECT credits FROM users WHERE email=?", (email,))
    row = cursor.fetchone()
    
    if not row:
        print(f"User {email} not found. Creating user...")
        cursor.execute("INSERT INTO users(email, credits) VALUES(?, ?)", (email, amount))
    else:
        new_credits = row[0] + amount
        cursor.execute("UPDATE users SET credits=? WHERE email=?", (new_credits, email))
        print(f"Updated credits for {email}. Old: {row[0]}, New: {new_credits}")

    # Log transaction
    cursor.execute(
        "INSERT INTO credit_transactions(email, delta, reason) VALUES(?, ?, ?)",
        (email, amount, "manual_admin_add")
    )
    
    conn.commit()
    conn.close()
    print("Done.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python add_credits.py <email> <amount>")
    else:
        email = sys.argv[1]
        amount = int(sys.argv[2])
        add_credits(email, amount)
