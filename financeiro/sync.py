import json
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    mode TEXT NOT NULL,
    report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'confirmed', 'review')),
    receipt TEXT
);
"""


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.open()) as db:
            db.executescript(SCHEMA)

    def open(self):
        return sqlite3.connect(self.path, timeout=10)

    def simulate(self, entries, errors):
        candidates, conflicts = {}, set()
        duplicates = 0
        for entry in entries:
            previous = candidates.get(entry.key)
            if previous is None:
                candidates[entry.key] = entry
            elif entry.payload() == previous.payload():
                duplicates += 1
            else:
                conflicts.add(entry.key)
        preview, review = [], []
        with closing(self.open()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for key, entry in candidates.items():
                previous = db.execute(
                    'SELECT payload, status FROM ledger WHERE key = ?', (key,)
                ).fetchone()
                if key in conflicts or (previous and previous != (entry.payload(), 'confirmed')):
                    review.append(key)
                elif previous:
                    duplicates += 1
                else:
                    preview.append(dict(json.loads(entry.payload()), sync_key=key))
            report = {
                'processed': len(entries) + len(errors),
                'sent': 0,
                'duplicates': duplicates,
                'errors': errors,
                'review': review,
                'preview': preview,
            }
            run = db.execute(
                'INSERT INTO runs (mode, report) VALUES (?, ?)',
                ('simulation', json.dumps(report, ensure_ascii=False)),
            )
            return dict(report, run_id=run.lastrowid)

    def runs(self):
        with closing(self.open()) as db:
            rows = db.execute('SELECT id, created_at, mode, report FROM runs ORDER BY id DESC LIMIT 100')
            return [dict(json.loads(report), run_id=key, utc=created_at, mode=mode)
                    for key, created_at, mode, report in rows]

    def send_to_test_destination(self, entry, destination, *, approved_payload):
        """Exercise creation and read-back against a test double."""
        key, payload = entry.key, entry.payload()
        if approved_payload != payload:
            raise ValueError('Conteúdo do lançamento sem aprovação')
        with closing(self.open()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute(
                'SELECT payload, status FROM ledger WHERE key = ?', (key,)
            ).fetchone()
            if previous == (payload, 'confirmed'):
                return 'duplicate'
            if previous:
                return 'review'
            db.execute(
                'INSERT INTO ledger(key, payload, status) VALUES (?, ?, ?)',
                (key, payload, 'pending'),
            )
        receipt = None
        try:
            receipt = destination.create(key, payload)
            confirmed = bool(receipt) and destination.read(receipt) == (key, payload)
        except Exception:
            confirmed = False
        status = 'confirmed' if confirmed else 'review'
        with closing(self.open()) as db, db:
            db.execute('UPDATE ledger SET status = ?, receipt = ? WHERE key = ?',
                       (status, receipt, key))
        return status

    def record(self, mode, report):
        with closing(self.open()) as db, db:
            run = db.execute(
                'INSERT INTO runs (mode, report) VALUES (?, ?)',
                (mode, json.dumps(report, ensure_ascii=False)),
            )
            return run.lastrowid
