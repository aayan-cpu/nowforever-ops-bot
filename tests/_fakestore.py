"""In-memory stand-in for app.store so reports/server can be tested without
hitting live Firestore. Install() swaps the public store functions for methods
backed by plain dicts; the returned object restores the originals on .restore().

Only the surface area the app actually uses is faked: list_all, get, patch,
create, delete, next_seq.
"""
from __future__ import annotations

from app import store


class FakeStore:
    # functions on app.store we override, so we can restore exactly these.
    _PATCHED = ("list_all", "get", "patch", "create", "delete", "next_seq")

    def __init__(self, messages=None, tasks=None, **collections):
        self.data: dict[str, list[dict]] = {
            "messages": [dict(m) for m in (messages or [])],
            "tasks": [dict(t) for t in (tasks or [])],
        }
        for name, rows in collections.items():
            self.data[name] = [dict(r) for r in rows]
        self._seq = 0
        self._orig: dict = {}

    # ---- faked store API (signatures mirror app.store) ----
    def list_all(self, collection, use_cache=True):
        return [dict(r) for r in self.data.get(collection, [])]

    def get(self, collection, doc_id):
        for r in self.data.get(collection, []):
            if str(r.get("id")) == str(doc_id):
                return dict(r)
        return None

    def patch(self, collection, doc_id, data):
        for r in self.data.get(collection, []):
            if str(r.get("id")) == str(doc_id):
                r.update(data)
                return dict(r)
        return None

    def create(self, collection, data, doc_id=None):
        rec = dict(data)
        if doc_id is not None:
            rec["id"] = doc_id
        self.data.setdefault(collection, []).append(rec)
        return dict(rec)

    def delete(self, collection, doc_id):
        rows = self.data.get(collection, [])
        self.data[collection] = [r for r in rows if str(r.get("id")) != str(doc_id)]

    def next_seq(self, name):
        self._seq += 1
        return self._seq

    # ---- install / restore ----
    def install(self):
        for fn in self._PATCHED:
            self._orig[fn] = getattr(store, fn)
            setattr(store, fn, getattr(self, fn))
        return self

    def restore(self):
        for fn, orig in self._orig.items():
            setattr(store, fn, orig)
        self._orig.clear()
