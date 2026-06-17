import unittest
from app import sync


class ToEventTests(unittest.TestCase):
    def test_maps_message_resource_to_event(self):
        m = {
            "name": "spaces/AAA/messages/xyz",
            "text": "Day report attached",
            "createTime": "2026-06-17T18:00:00Z",
            "sender": {"name": "users/1", "displayName": "Abdul", "email": "abdul@nowandforever.com"},
            "attachment": [{"name": "att1"}],
        }
        ev = sync.to_event("spaces/AAA", m)
        self.assertEqual(ev["type"], "MESSAGE")
        self.assertEqual(ev["space"]["name"], "spaces/AAA")
        self.assertEqual(ev["message"]["name"], "spaces/AAA/messages/xyz")
        self.assertEqual(ev["message"]["text"], "Day report attached")
        self.assertEqual(ev["message"]["sender"]["email"], "abdul@nowandforever.com")
        self.assertEqual(ev["user"]["displayName"], "Abdul")
        self.assertEqual(ev["message"]["attachment"], [{"name": "att1"}])

    def test_falls_back_to_argument_text(self):
        ev = sync.to_event("spaces/B", {"name": "n", "argumentText": "hello"})
        self.assertEqual(ev["message"]["text"], "hello")

    def test_empty_text_is_blank_not_none(self):
        ev = sync.to_event("spaces/B", {"name": "n"})
        self.assertEqual(ev["message"]["text"], "")


if __name__ == "__main__":
    unittest.main()
