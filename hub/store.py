import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sources (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
 category TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL, canonical TEXT NOT NULL UNIQUE,
 content TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '', published_at TEXT NOT NULL,
 source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL, notes TEXT NOT NULL DEFAULT '',
 favorite INTEGER NOT NULL DEFAULT 0, fingerprint TEXT UNIQUE, revision INTEGER NOT NULL DEFAULT 1,
 analysis TEXT, category TEXT, score INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL, analysis TEXT NOT NULL, kind TEXT NOT NULL, model TEXT,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_date ON items(published_at);
CREATE INDEX IF NOT EXISTS items_score ON items(score);
'''

def db_path():
    return Path(os.getenv('HUB_DB', str(Path(__file__).resolve().parent.parent / 'data' / 'hub.sqlite3')))

@contextmanager
def db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init():
    with db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript(SCHEMA)

def item(row):
    result = dict(row)
    result['analysis'] = json.loads(result['analysis']) if result['analysis'] else None
    return result
