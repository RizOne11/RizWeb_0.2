import sqlite3
import time


class Cache:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, html TEXT, ts REAL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS searches(cache_key TEXT PRIMARY KEY, payload TEXT, ts REAL)"
        )
        self.db.commit()

    def get(self, url, max_age=86400):
        r = self.db.execute("SELECT html,ts FROM pages WHERE url=?", (url,)).fetchone()
        return r[0] if r and time.time() - r[1] < max_age else None

    def put(self, url, html):
        self.db.execute(
            "INSERT OR REPLACE INTO pages VALUES(?,?,?)", (url, html, time.time())
        )
        self.db.commit()

    def get_search(self, cache_key, max_age=259200):
        r = self.db.execute(
            "SELECT payload,ts FROM searches WHERE cache_key=?", (cache_key,)
        ).fetchone()
        return r[0] if r and time.time() - r[1] < max_age else None

    def put_search(self, cache_key, payload):
        self.db.execute(
            "INSERT OR REPLACE INTO searches VALUES(?,?,?)",
            (cache_key, payload, time.time()),
        )
        self.db.commit()
