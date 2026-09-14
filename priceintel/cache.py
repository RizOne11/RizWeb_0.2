import sqlite3
import time
import threading


class Cache:
    def __init__(self, path):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        with self._lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, html TEXT, ts REAL)")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS searches(cache_key TEXT PRIMARY KEY, payload TEXT, ts REAL)"
            )
            self.db.commit()

    def get(self, url, max_age=86400):
        with self._lock:
            r = self.db.execute("SELECT html,ts FROM pages WHERE url=?", (url,)).fetchone()
        return r[0] if r and time.time() - r[1] < max_age else None

    def put(self, url, html):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO pages VALUES(?,?,?)", (url, html, time.time())
            )
            self.db.commit()

    def get_search(self, cache_key, max_age=259200):
        with self._lock:
            r = self.db.execute(
                "SELECT payload,ts FROM searches WHERE cache_key=?", (cache_key,)
            ).fetchone()
        return r[0] if r and time.time() - r[1] < max_age else None

    def put_search(self, cache_key, payload):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO searches VALUES(?,?,?)",
                (cache_key, payload, time.time()),
            )
            self.db.commit()
