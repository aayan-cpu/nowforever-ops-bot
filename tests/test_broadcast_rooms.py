import unittest
from app.brain import _rooms_from_messages


class RoomsFromMessagesTests(unittest.TestCase):
    def test_distinct_rooms_first_name_wins(self):
        msgs = [
            {"room_id": "spaces/A", "room_name": "4 Channelview"},
            {"room_id": "spaces/A", "room_name": "4 Channelview (alt)"},
            {"room_id": "spaces/B", "room_name": "11 Windchase"},
        ]
        rooms = dict(_rooms_from_messages(msgs, set()))
        self.assertEqual(rooms, {"spaces/A": "4 Channelview", "spaces/B": "11 Windchase"})

    def test_excludes_dm_spaces(self):
        msgs = [
            {"room_id": "spaces/ROOM", "room_name": "8 Parker"},
            {"room_id": "spaces/DM1", "room_name": "Aayan"},
        ]
        rooms = dict(_rooms_from_messages(msgs, {"spaces/DM1"}))
        self.assertEqual(rooms, {"spaces/ROOM": "8 Parker"})

    def test_ignores_non_space_ids(self):
        msgs = [{"room_id": "", "room_name": "x"}, {"room_id": "weird", "room_name": "y"}]
        self.assertEqual(_rooms_from_messages(msgs, set()), [])

    def test_empty(self):
        self.assertEqual(_rooms_from_messages([], set()), [])
        self.assertEqual(_rooms_from_messages(None, set()), [])


if __name__ == "__main__":
    unittest.main()
