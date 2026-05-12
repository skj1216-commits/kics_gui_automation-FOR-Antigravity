import sqlite3


DB_FILE = "processed_docs.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE NOT NULL,
            user_id TEXT,
            processed_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def is_processed(doc_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM processed_docs WHERE doc_id = ?", (doc_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    return row[0] == "SUCCESS"


def mark_processed(doc_id, user_id, status="SUCCESS"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO processed_docs (doc_id, user_id, status)
        VALUES (?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
            user_id=excluded.user_id,
            status=excluded.status,
            processed_time=CURRENT_TIMESTAMP
        """,
        (doc_id, user_id, status),
    )
    conn.commit()
    conn.close()


def get_all_processed_docs():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT doc_id, user_id, processed_time, status
        FROM processed_docs
        ORDER BY processed_time DESC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    init_db()
