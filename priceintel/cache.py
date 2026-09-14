import sqlite3, time
class Cache:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, html TEXT, ts REAL)")
    def get(self,url,max_age=86400):
        r=self.db.execute("SELECT html,ts FROM pages WHERE url=?",(url,)).fetchone()
        return r[0] if r and time.time()-r[1] < max_age else None
    def put(self,url,html):
        self.db.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?)",(url,html,time.time())); self.db.commit()
