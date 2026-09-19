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
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS identities("
                "identity_key TEXT, source TEXT, url TEXT, title TEXT, product_id TEXT, confidence TEXT, "
                "identity_version TEXT DEFAULT '', ts REAL, "
                "PRIMARY KEY(identity_key, source, url))"
            )
            columns = {
                row[1] for row in self.db.execute("PRAGMA table_info(identities)").fetchall()
            }
            if "identity_version" not in columns:
                self.db.execute(
                    "ALTER TABLE identities ADD COLUMN identity_version TEXT DEFAULT ''"
                )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_identities_lookup "
                "ON identities(identity_key, source, identity_version, ts)"
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


    def get_identities(
        self,
        identity_key,
        source,
        max_age=2592000,
        limit=24,
        identity_version=None,
    ):
        cutoff = time.time() - max_age
        params = [identity_key, source, cutoff]
        version_sql = ""
        if identity_version is not None:
            version_sql = " AND identity_version=?"
            params.append(str(identity_version))
        params.append(int(limit))
        with self._lock:
            rows = self.db.execute(
                "SELECT url,title,product_id,confidence,identity_version,ts FROM identities "
                "WHERE identity_key=? AND source=? AND ts>=?" + version_sql + " "
                "ORDER BY CASE confidence WHEN 'CONFIRMED' THEN 0 WHEN 'PROBABLE' THEN 1 ELSE 2 END, "
                "ts DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [
            {
                "url": row[0],
                "title": row[1] or "",
                "product_id": row[2] or "",
                "confidence": row[3] or "",
                "identity_version": row[4] or "",
                "ts": row[5],
            }
            for row in rows
        ]

    def put_identity(
        self,
        identity_key,
        source,
        url,
        title="",
        product_id="",
        confidence="CONFIRMED",
        identity_version="",
    ):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO identities("
                "identity_key,source,url,title,product_id,confidence,identity_version,ts"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (
                    identity_key,
                    source,
                    url,
                    title,
                    product_id,
                    confidence,
                    identity_version,
                    time.time(),
                ),
            )
            self.db.commit()

    def delete_identity(self, identity_key, source, url):
        with self._lock:
            self.db.execute(
                "DELETE FROM identities WHERE identity_key=? AND source=? AND url=?",
                (identity_key, source, url),
            )
            self.db.commit()
