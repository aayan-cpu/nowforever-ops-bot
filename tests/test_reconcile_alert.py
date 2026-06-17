"""Tests for the proactive reconciliation alert job
(WORK.md: 'Proactive reconciliation alerts').

Run: `py -m unittest tests.test_reconcile_alert` from the repo root.

The job builds on app/reconcile.py (flagged discrepancies + summary) and DMs
admins. We patch the reconcile lookups, the admin-DM targets, and the chat
poster, so nothing touches Firestore or the network.
"""
import unittest

from app import digests, reconcile


class _Patch:
    def __init__(self, flagged, summary="[A] BOL 8000 vs Veeder 5500 (off 2500)"):
        self.flagged = flagged
        self.summary = summary
        self.posts = []

    def __enter__(self):
        self._orig = (reconcile.discrepancies, reconcile.summarize,
                      digests._admin_dms, digests.chat_media.post_to_space)
        reconcile.discrepancies = lambda *a, **k: self.flagged
        reconcile.summarize = lambda *a, **k: self.summary
        digests._admin_dms = lambda: [{"email": "owner", "space": "spaces/DM1"}]
        digests.chat_media.post_to_space = lambda space, text: (self.posts.append((space, text)) or True)
        return self

    def __exit__(self, *a):
        (reconcile.discrepancies, reconcile.summarize,
         digests._admin_dms, digests.chat_media.post_to_space) = self._orig


class ReconcileAlertTests(unittest.TestCase):
    def test_alerts_admins_when_flagged(self):
        with _Patch(flagged=[{"site": "4 Channelview"}]) as p:
            res = digests.reconcile_alert()
        self.assertEqual(res["flagged"], 1)
        self.assertEqual(res["sent"], 1)
        self.assertTrue(res["ok"])
        space, text = p.posts[0]
        self.assertEqual(space, "spaces/DM1")
        self.assertIn("reconciliation alert", text.lower())
        self.assertIn("2500", text)  # from the summary

    def test_quiet_when_nothing_flagged(self):
        with _Patch(flagged=[]) as p:
            res = digests.reconcile_alert()
        self.assertEqual(res["flagged"], 0)
        self.assertEqual(p.posts, [])

    def test_registered_as_cron_job(self):
        self.assertIs(digests.JOBS.get("reconcile-alert"), digests.reconcile_alert)


if __name__ == "__main__":
    unittest.main()
