import unittest
from app import org


class RoomPurposeTests(unittest.TestCase):
    def test_all_captains(self):
        self.assertEqual(org.room_purpose("All Captains Chat"), "all-captains")

    def test_marketing(self):
        self.assertEqual(org.room_purpose("MARKETING"), "marketing")

    def test_store(self):
        self.assertEqual(org.room_purpose("4 Channelview"), "store")
        self.assertEqual(org.room_purpose("11 N&F Windchase"), "store")

    def test_empty_other(self):
        self.assertEqual(org.room_purpose(""), "other")


class DescribeRoomsTests(unittest.TestCase):
    def test_maps_store_and_purpose(self):
        rooms = [("spaces/A", "4 Channelview"), ("spaces/C", "All Captains Chat")]
        out = {d["room_name"]: d for d in org.describe_rooms(rooms)}
        self.assertEqual(out["4 Channelview"]["purpose"], "store")
        self.assertTrue(out["4 Channelview"]["store"])           # canonical store resolved
        self.assertEqual(out["All Captains Chat"]["purpose"], "all-captains")
        self.assertIsNone(out["All Captains Chat"]["store"])


class RosterTests(unittest.TestCase):
    def test_home_store_is_most_active_station(self):
        msgs = [
            {"sender": "Abdul", "room_name": "4 Channelview"},
            {"sender": "Abdul", "room_name": "4 Channelview"},
            {"sender": "Abdul", "room_name": "11 N&F Windchase"},
        ]
        r = org.roster(msgs)
        self.assertEqual(r["Abdul"]["messages"], 3)
        self.assertIn("Channelview", r["Abdul"]["home_store"])

    def test_admin_flag(self):
        msgs = [{"sender": "aayan@khawarsons.com", "room_name": "4 Channelview"}]
        r = org.roster(msgs, admin_emails={"aayan@khawarsons.com"})
        self.assertTrue(r["aayan@khawarsons.com"]["is_admin"])

    def test_skips_transcript_noise(self):
        msgs = [{"sender": "Updated on", "room_name": "4 Channelview"}]
        self.assertEqual(org.roster(msgs), {})


class ManagerByStoreTests(unittest.TestCase):
    def test_admin_n_mention_maps_to_store(self):
        msgs = [{"assigned_hint": "Admin 4"}, {"assigned_hint": "Admin 4, Moin"}]
        self.assertEqual(org.manager_by_store(msgs), {"4": ["Admin 4"]})


if __name__ == "__main__":
    unittest.main()
