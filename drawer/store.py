"""Encrypted local storage for Drawer.

Safety rules baked in:
  * Everything a person says (names, places, phones, notes) is encrypted.
  * Purchase, return and warranty dates and incident times are encrypted too.
  * Each household gets its own key derived from the master key, so a bug
    that reads another household's row cannot decrypt it.
  * Household names are stored only as a keyed hash (HMAC with the master key).
  * Tokens, codes and passphrases are stored only as hashes.
  * wipe() removes the household and revokes every token.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

STOPWORDS = {"the", "for", "and", "who", "where", "what", "call", "are", "was", "with", "this",
             "that", "you", "does", "from", "into", "our", "his", "her", "can", "should", "need"}
WORDS = ["maple", "river", "cedar", "amber", "slate", "heron", "linen", "quartz",
         "fennel", "harbor", "willow", "copper", "meadow", "pebble", "saffron", "tundra"]
MAX_ENTRIES = 500
MAX_INCIDENTS = 200


def _home() -> Path:
    return Path(os.environ.get("DRAWER_HOME", Path.home() / ".drawer"))


def _master_key() -> bytes:
    kms_id = os.environ.get("DRAWER_KMS_KEY_ID")
    if kms_id:
        from . import kms
        return kms.master_key(_home(), kms_id)
    env = os.environ.get("DRAWER_KEY")
    if env:
        return base64.urlsafe_b64decode(env.encode())
    path = _home() / "key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return base64.urlsafe_b64decode(path.read_bytes().strip())


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _scrypt(pw: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


class Store:
    def __init__(self, db_path: str | None = None, master: bytes | None = None):
        _home().mkdir(parents=True, exist_ok=True)
        self.master = master or _master_key()
        self.lock = threading.RLock()
        self.db_file = db_path or str(_home() / "drawer.db")
        self.db = sqlite3.connect(self.db_file, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS households(
                id TEXT PRIMARY KEY, name_key TEXT UNIQUE NOT NULL,
                salt BLOB NOT NULL, pass_hash BLOB NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens(
                token_hash TEXT PRIMARY KEY, household_id TEXT NOT NULL,
                scope TEXT NOT NULL, kind TEXT NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS codes(
                code_hash TEXT PRIMARY KEY, household_id TEXT NOT NULL, scope TEXT NOT NULL,
                challenge TEXT NOT NULL, redirect_uri TEXT NOT NULL, client_id TEXT NOT NULL,
                expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS guest_passes(
                code_hash TEXT PRIMARY KEY, household_id TEXT NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS entries(
                id INTEGER PRIMARY KEY AUTOINCREMENT, household_id TEXT NOT NULL,
                kind TEXT NOT NULL, secret BLOB NOT NULL,
                purchased_on TEXT, return_by TEXT, warranty_until TEXT,
                status TEXT NOT NULL DEFAULT 'open', guest_ok INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS entries_by_house ON entries(household_id);
            CREATE TABLE IF NOT EXISTS incidents(
                id INTEGER PRIMARY KEY AUTOINCREMENT, household_id TEXT NOT NULL,
                at TEXT NOT NULL, secret BLOB NOT NULL);
            """
        )
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.commit()
        for p, mode in ((_home(), 0o700), (Path(self.db_file), 0o600)):
            try:
                p.chmod(mode)
            except OSError:
                pass

    # ---- encryption, one key per household
    def _fernet(self, hid: str) -> Fernet:
        k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                 info=b"drawer:" + hid.encode()).derive(self.master)
        return Fernet(base64.urlsafe_b64encode(k))

    def _seal(self, hid, data: dict) -> bytes:
        return self._fernet(hid).encrypt(json.dumps(data).encode())

    def _unseal(self, hid, blob: bytes) -> dict:
        return json.loads(self._fernet(hid).decrypt(blob))

    def _name_key(self, name: str) -> str:
        return hmac.new(self.master, b"name:" + name.strip().lower().encode(), hashlib.sha256).hexdigest()

    # ---- households
    def create_household(self, name: str, passphrase: str) -> str | None:
        key = self._name_key(name)
        salt = secrets.token_bytes(16)
        hid = secrets.token_hex(8)
        with self.lock:
            try:
                self.db.execute(
                    "INSERT INTO households VALUES (?,?,?,?,?)",
                    (hid, key, salt, _scrypt(passphrase, salt), date.today().isoformat()))
                self.db.commit()
            except sqlite3.IntegrityError:
                return None
        return hid

    def verify_household(self, name: str, passphrase: str) -> str | None:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM households WHERE name_key=?", (self._name_key(name),)).fetchone()
        salt = row["salt"] if row else b"\0" * 16
        got = _scrypt(passphrase, salt)  # always do the work, so timing does not leak
        if row and hmac.compare_digest(got, row["pass_hash"]):
            return row["id"]
        return None

    def household_count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM households").fetchone()[0]

    def household_exists(self, hid: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM households WHERE id=?", (hid,)).fetchone() is not None

    # ---- tokens and codes
    def issue_token(self, hid, scope, kind="access", ttl=3600) -> str:
        raw = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("INSERT INTO tokens VALUES (?,?,?,?,?)",
                            (_h(raw), hid, scope, kind, time.time() + ttl))
            self.db.commit()
        return raw

    def lookup_token(self, raw: str, kind="access"):
        with self.lock:
            row = self.db.execute("SELECT * FROM tokens WHERE token_hash=? AND kind=?",
                                  (_h(raw), kind)).fetchone()
        if not row or row["expires_at"] < time.time() or not self.household_exists(row["household_id"]):
            return None
        return row["household_id"], row["scope"], row["expires_at"]

    def revoke_token(self, raw: str):
        with self.lock:
            self.db.execute("DELETE FROM tokens WHERE token_hash=?", (_h(raw),))
            self.db.commit()

    def purge_expired(self):
        now = time.time()
        with self.lock:
            for t in ("tokens", "codes", "guest_passes"):
                self.db.execute(f"DELETE FROM {t} WHERE expires_at < ?", (now,))
            self.db.commit()

    def create_code(self, hid, scope, challenge, redirect_uri, client_id) -> str:
        raw = secrets.token_urlsafe(24)
        with self.lock:
            self.db.execute("INSERT INTO codes VALUES (?,?,?,?,?,?,?)",
                            (_h(raw), hid, scope, challenge, redirect_uri, client_id, time.time() + 120))
            self.db.commit()
        return raw

    def pop_code(self, raw: str):
        with self.lock:
            row = self.db.execute("SELECT * FROM codes WHERE code_hash=?", (_h(raw),)).fetchone()
            self.db.execute("DELETE FROM codes WHERE code_hash=?", (_h(raw),))
            self.db.commit()
        if not row or row["expires_at"] < time.time():
            return None
        return dict(row)

    # ---- guest passes
    def create_guest_pass(self, hid, hours: int) -> str:
        code = "-".join([secrets.choice(WORDS), secrets.choice(WORDS), secrets.choice(WORDS),
                         f"{secrets.randbelow(10000):04d}"])
        with self.lock:
            self.db.execute("INSERT INTO guest_passes VALUES (?,?,?)",
                            (_h(code), hid, time.time() + hours * 3600))
            self.db.commit()
        return code

    def use_guest_code(self, code: str):
        with self.lock:
            row = self.db.execute("SELECT * FROM guest_passes WHERE code_hash=?",
                                  (_h(code.strip().lower()),)).fetchone()
        if not row or row["expires_at"] < time.time():
            return None
        return row["household_id"], row["expires_at"]

    def end_guest_passes(self, hid) -> int:
        with self.lock:
            hashes_ = [r[0] for r in self.db.execute(
                "SELECT code_hash FROM guest_passes WHERE household_id=?", (hid,))]
            self.db.execute("DELETE FROM guest_passes WHERE household_id=?", (hid,))
            self.db.execute("DELETE FROM tokens WHERE household_id=? AND scope='guest'", (hid,))
            self.db.commit()
        return len(hashes_)

    # ---- entries (dates live inside the encrypted blob under "_d")
    def add_entry(self, hid, kind, data, purchased_on=None, return_by=None,
                  warranty_until=None, guest_ok=False) -> int:
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM entries WHERE household_id=?", (hid,)).fetchone()[0]
            if n >= MAX_ENTRIES:
                raise ValueError("Your drawer is full.")
            data = {**data, "_d": [purchased_on, return_by, warranty_until]}
            cur = self.db.execute(
                "INSERT INTO entries(household_id,kind,secret,guest_ok) VALUES (?,?,?,?)",
                (hid, kind, self._seal(hid, data), int(guest_ok)))
            self.db.commit()
            return cur.lastrowid

    def entries(self, hid, kind=None, guest_only=False):
        q, a = "SELECT * FROM entries WHERE household_id=?", [hid]
        if kind:
            q += " AND kind=?"
            a.append(kind)
        if guest_only:
            q += " AND guest_ok=1"
        with self.lock:
            rows = self.db.execute(q, a).fetchall()
        out = []
        for r in rows:
            d = self._unseal(hid, r["secret"])
            # rows made by older versions kept the dates in plain columns
            pd, rb, wu = d.pop("_d", [r["purchased_on"], r["return_by"], r["warranty_until"]])
            out.append({"id": r["id"], "kind": r["kind"], **d, "purchased_on": pd, "return_by": rb,
                        "warranty_until": wu, "status": r["status"], "guest_ok": bool(r["guest_ok"])})
        return out

    def set_status(self, hid, entry_id, status) -> bool:
        with self.lock:
            cur = self.db.execute("UPDATE entries SET status=? WHERE id=? AND household_id=?",
                                  (status, entry_id, hid))
            self.db.commit()
            return cur.rowcount == 1

    def closing(self, hid, today: date, within_days: int):
        limit = (today + timedelta(days=within_days)).isoformat()
        out = []
        for e in self.entries(hid, "purchase"):
            if e["status"] != "open":
                continue
            for kind, key in (("return window", "return_by"), ("warranty", "warranty_until")):
                d = e[key]
                if d and today.isoformat() <= d <= limit:
                    out.append({**e, "what": kind, "deadline": d,
                                "days_left": (date.fromisoformat(d) - today).days})
        return sorted(out, key=lambda x: x["deadline"])

    def search(self, hid, query, kinds=None, guest_only=False):
        words = [w for w in "".join(c if c.isalnum() else " " for c in query.lower()).split()
                 if len(w) > 2 and w not in STOPWORDS]
        if not words:
            return []
        res = []
        for e in self.entries(hid, guest_only=guest_only):
            if kinds and e["kind"] not in kinds:
                continue
            hay = " ".join(str(e.get(f) or "") for f in ("name", "where", "store", "note", "location", "trade"))
            hay_words = set("".join(c if c.isalnum() else " " for c in hay.lower()).split())
            if any(w in hay_words or any(h.startswith(w) for h in hay_words) for w in words):
                res.append(e)
        return res

    # ---- incidents (time lives inside the encrypted blob)
    def log_incident(self, hid, data: dict) -> int:
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM incidents WHERE household_id=?", (hid,)).fetchone()[0]
            if n >= MAX_INCIDENTS:
                self.db.execute(
                    "DELETE FROM incidents WHERE id IN (SELECT id FROM incidents WHERE household_id=? "
                    "ORDER BY id LIMIT ?)", (hid, n - MAX_INCIDENTS + 1))
            blob = self._seal(hid, {**data, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            cur = self.db.execute("INSERT INTO incidents(household_id,at,secret) VALUES (?,?,?)",
                                  (hid, "", blob))
            self.db.commit()
            return cur.lastrowid

    def incidents(self, hid):
        with self.lock:
            rows = self.db.execute("SELECT * FROM incidents WHERE household_id=? ORDER BY id DESC",
                                   (hid,)).fetchall()
        out = []
        for r in rows:
            d = self._unseal(hid, r["secret"])
            d.setdefault("at", r["at"])
            out.append({"id": r["id"], **d})
        return out

    # ---- the big red button
    def wipe(self, hid) -> int:
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM entries WHERE household_id=?", (hid,)).fetchone()[0]
            for t in ("entries", "incidents", "tokens", "codes", "guest_passes"):
                self.db.execute(f"DELETE FROM {t} WHERE household_id=?", (hid,))
            self.db.execute("DELETE FROM households WHERE id=?", (hid,))
            self.db.commit()
            self.db.execute("VACUUM")
        return n
