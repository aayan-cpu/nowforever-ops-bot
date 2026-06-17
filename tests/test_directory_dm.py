import io
import json
import unittest
import urllib.request

from app import directory, chat_media


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()
    def read(self):
        return self._b


class ColdDmTests(unittest.TestCase):
    def setUp(self):
        self._tok = chat_media.get_chat_token
        self._open = urllib.request.urlopen
        self._find = directory.find_dm_space
        chat_media.get_chat_token = lambda: "tok"
        self.captured = {}
        def fake_open(req, *a, **k):
            self.captured["url"] = req.full_url
            self.captured["method"] = req.get_method()
            self.captured["body"] = json.loads(req.data.decode()) if req.data else None
            return _FakeResp({"name": "spaces/DM123"})
        urllib.request.urlopen = fake_open

    def tearDown(self):
        chat_media.get_chat_token = self._tok
        urllib.request.urlopen = self._open
        directory.find_dm_space = self._find

    def test_create_dm_builds_direct_message_setup(self):
        space = directory.create_dm_space("u-42")
        self.assertEqual(space, "spaces/DM123")
        self.assertIn("spaces:setup", self.captured["url"])
        self.assertEqual(self.captured["method"], "POST")
        self.assertEqual(self.captured["body"]["space"]["spaceType"], "DIRECT_MESSAGE")
        members = self.captured["body"]["memberships"]
        self.assertEqual(members[0]["member"]["name"], "users/u-42")
        self.assertEqual(members[0]["member"]["type"], "HUMAN")

    def test_ensure_dm_creates_when_none_exists(self):
        directory.find_dm_space = lambda uid: None  # no existing DM
        try:
            space = directory.ensure_dm_space("u-7")
            self.assertEqual(space, "spaces/DM123")          # fell back to create
            self.assertIn("spaces:setup", self.captured["url"])
        finally:
            pass

    def test_ensure_dm_prefers_existing(self):
        directory.find_dm_space = lambda uid: "spaces/EXISTING"
        self.captured.clear()
        space = directory.ensure_dm_space("u-7")
        self.assertEqual(space, "spaces/EXISTING")
        self.assertEqual(self.captured, {})  # never called setup


if __name__ == "__main__":
    unittest.main()
