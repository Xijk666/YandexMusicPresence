import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from catalog import lookup, select_exact
from core import Track


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.track = Track("source", "Song", "Artist", "Album", "playing", 0, 200, 0)
        self.cover = "avatars.yandex.net/get-music-content/123/album/%%"
        self.item = dict(id=12, title="Song", artists=[dict(name="Artist")],
                         albums=[dict(id=34, title="Album", coverUri=self.cover)], durationMs=200000)

    def test_album_cover_when_track_has_no_cover(self):
        self.assertTrue(select_exact(self.track, [self.item])["cover"].endswith("/400x400"))

    def test_invalid_track_cover_falls_back_to_valid_album_cover(self):
        self.item["coverUri"] = "https://example.com/wrong.png"
        self.assertIn("avatars.yandex.net", select_exact(self.track, [self.item])["cover"])

    def test_duplicate_releases_with_same_cover_keep_image_without_link(self):
        result = select_exact(self.track, [self.item, {**self.item, "id": 13}])
        self.assertIn("cover", result)
        self.assertNotIn("url", result)

    def test_different_covers_remain_ambiguous(self):
        other = copy.deepcopy(self.item)
        other["id"] = 13
        other["albums"][0]["coverUri"] = "avatars.yandex.net/get-music-content/123/other/%%"
        self.assertEqual(select_exact(self.track, [self.item, other]), {})

    def test_missing_cover_on_one_duplicate_does_not_claim_consensus(self):
        other = copy.deepcopy(self.item)
        other["id"] = 13
        del other["albums"][0]["coverUri"]
        self.assertEqual(select_exact(self.track, [self.item, other]), {})

    def test_collaborator_order_can_differ(self):
        from dataclasses import replace
        self.item["artists"] = [dict(name="Guest"), dict(name="Artist")]
        self.assertTrue(select_exact(replace(self.track, artist="Artist, Guest"), [self.item]))
        self.assertEqual(select_exact(replace(self.track, artist="Artist, Other"), [self.item]), {})

    def response(self):
        return io.BytesIO(json.dumps(dict(result=dict(tracks=dict(results=[self.item])))).encode())

    @patch("catalog.local_match", return_value={})
    def test_unavailable_endpoint_uses_second_public_endpoint(self, local):
        error = HTTPError("https://api.music.yandex.ru", 451, "Unavailable", {}, None)
        with patch("catalog.urllib.request.urlopen", side_effect=[error, self.response()]) as request:
            self.assertIn("cover", lookup(self.track))
        self.assertEqual(request.call_count, 2)
        self.assertIn("api.music.yandex.net", request.call_args.args[0].full_url)

    @patch("catalog.local_match", return_value={})
    def test_temporary_failure_does_not_poison_next_lookup(self, local):
        with patch("catalog.urllib.request.urlopen", side_effect=[TimeoutError(), TimeoutError(), self.response()]):
            self.assertEqual(lookup(self.track), {})
            self.assertIn("cover", lookup(self.track))

    @patch("catalog.local_match", return_value={})
    def test_disabled_online_lookup_sends_no_request(self, local):
        with patch("catalog.urllib.request.urlopen") as request:
            self.assertEqual(lookup(self.track, online=False), {})
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
