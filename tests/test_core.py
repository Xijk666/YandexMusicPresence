import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import unittest
from core import Timeline, Track, activity, clock, cover_url, is_yandex
from catalog import select_exact

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.timeline = Timeline()
        self.args = dict(source="yandexmusic.exe", title="Track", artist="Artist", album="Album",
                         status="playing", raw_position=60., duration=200., updated=1_780_000_000.,
                         wall=1_780_000_002., mono=10.)

    def sample(self, **kwargs):
        return self.timeline.sample(**{**self.args, **kwargs})

    def test_extrapolates_from_last_updated(self):
        t = self.sample()
        self.assertEqual(t.position, 62)
        self.assertEqual(t.at(15), 67)

    def test_same_anchor_does_not_double_count(self):
        self.sample()
        t = self.sample(wall=1_780_000_006., mono=14)
        self.assertEqual(t.position, 66)

    def test_pause_without_new_anchor_freezes(self):
        self.sample()
        paused = self.sample(status="paused", mono=15, wall=1_780_000_007.)
        self.assertEqual(paused.at(100), 67)
        still = self.sample(status="paused", mono=20, wall=1_780_000_012.)
        self.assertEqual(still.position, 67)

    def test_resume_excludes_pause_time(self):
        self.sample()
        self.sample(status="paused", mono=15, wall=1_780_000_007.)
        resumed = self.sample(mono=100, wall=1_780_000_092.)
        self.assertEqual(resumed.at(102), 69)

    def test_seek_forward_and_back(self):
        self.sample()
        self.assertEqual(self.sample(raw_position=150, updated=1_780_000_004., wall=1_780_000_004., mono=12).position, 150)
        self.assertEqual(self.sample(raw_position=12, updated=1_780_000_005., wall=1_780_000_005., mono=13).position, 12)

    def test_legacy_empty_timeline_is_unknown(self):
        self.assertIsNone(self.sample(raw_position=0, duration=0, updated=-11644473600).position)

    def test_end_clamped(self):
        self.assertEqual(self.sample(raw_position=199).at(100), 200)

    def test_new_track_resets(self):
        self.sample()
        self.assertEqual(self.sample(title="Other", raw_position=0, updated=1_780_000_002.).position, 0)

    def test_invalid_values(self):
        self.assertIsNone(self.sample(raw_position=float('nan')).position)
        self.assertIsNone(self.sample(duration=float('inf')).position)
        self.assertIsNone(self.sample(updated=1_780_000_030.).position)

    def test_rate(self):
        self.assertEqual(self.sample(rate=2).at(11), 66)

class PayloadTests(unittest.TestCase):
    def track(self, **kw):
        return Track(**{**dict(source="YandexMusic", title="Название", artist="Исполнитель", album="Альбом",
                              status="playing", position=65., duration=200., observed=10.), **kw})

    def test_listening_timestamps(self):
        p = activity(self.track(), wall=1000, mono=15)
        self.assertEqual(p['type'], 2)
        self.assertEqual(p['timestamps'], {'start': 930, 'end': 1130})

    def test_pause_has_fixed_time_no_timestamps(self):
        p = activity(self.track(status="paused"), wall=1000, mono=15)
        self.assertNotIn('timestamps', p)
        self.assertEqual(p['type'], 2, 'Pause must remain Listening to coexist with game activity')
        self.assertIn('1:05 / 3:20', p['state'])

    def test_playing_text_does_not_duplicate_native_progress_bar(self):
        p = activity(self.track(), wall=1000, mono=15)
        self.assertEqual(p['state'], 'Исполнитель')
        self.assertEqual(p['timestamps'], {'start': 930, 'end': 1130})

    def test_pause_resume_does_not_switch_activity_category(self):
        p = activity(self.track(), wall=1000, mono=15)
        paused = activity(self.track(status='paused'), wall=1000, mono=15)
        self.assertEqual((p['type'], paused['type']), (2, 2))
        self.assertIn('Пауза', paused['state'])
        self.assertNotIn('timestamps', paused)

    def test_unknown_time_not_invented_from_catalog_duration(self):
        p = activity(self.track(position=None, duration=None), {'duration': 200}, mono=15)
        self.assertNotIn('timestamps', p)

    def test_clear_for_buffering_stopped_closed(self):
        for status in ('buffering', 'stopped', 'closed', 'unknown'):
            self.assertIsNone(activity(self.track(status=status)))
        self.assertIsNone(activity(None))

    def test_speed_timer_is_hidden(self):
        self.assertNotIn('timestamps', activity(self.track(rate=1.5), mono=15))

    def test_urls_and_unicode(self):
        p = activity(self.track(title="🎵" * 200), {'url':'https://evil.example/test','cover':'https://evil.example/test'})
        self.assertNotIn('buttons', p)
        self.assertLessEqual(len(p['details'].encode('utf-16-le'))//2,128)
        self.assertEqual(cover_url('avatars.yandex.net/get-music/x/%%'), 'https://avatars.yandex.net/get-music/x/400x400')
        self.assertEqual(cover_url('avatars.yandex.net.evil.com/x'), '')

    def test_source_filter(self):
        self.assertTrue(is_yandex('A025C540.Yandex.Music_vfvw9svesycw6!App'))
        self.assertTrue(is_yandex('YandexMusic.exe'))
        self.assertTrue(is_yandex('ru.yandex.desktop.music'))
        self.assertFalse(is_yandex('chrome.exe'))
        self.assertFalse(is_yandex('Spotify.exe'))

    def test_clock(self):
        self.assertEqual(clock(3661), '1:01:01')
        self.assertEqual(clock(None), '—:—')

class MatchTests(unittest.TestCase):
    def setUp(self):
        self.t = Track('source','Song','Artist','Album','playing',0,200,0)
        self.item = dict(id=12,title='Song',artists=[{'name':'Artist'}],albums=[{'id':34,'title':'Album'}],durationMs=200000)

    def test_exact(self):
        self.assertEqual(select_exact(self.t,[self.item])['url'], 'https://music.yandex.ru/album/34/track/12')

    def test_ambiguous_rejected(self):
        self.assertEqual(select_exact(self.t,[self.item,{**self.item,'id':13}]),{})

    def test_modern_player_without_album_uses_duration_and_unique_match(self):
        from dataclasses import replace
        self.assertTrue(select_exact(replace(self.t,album=''),[self.item]))
        self.assertEqual(select_exact(replace(self.t,album='',duration=None),[self.item]),{})

    def test_wrong_artist_album_version_duration_rejected(self):
        for update in ({'artists':[{'name':'Other'}]}, {'albums':[{'id':34,'title':'Other'}]}, {'version':'live'}, {'durationMs':210000}):
            self.assertEqual(select_exact(self.t,[{**self.item,**update}]),{})

if __name__ == '__main__':
    unittest.main()
