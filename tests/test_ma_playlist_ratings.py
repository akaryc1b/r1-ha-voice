"""真实 MA 歌单方法的可选收藏查询预算、取消及认证边界。"""
import ast
import asyncio
import logging
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from music_assistant_models.enums import MediaType
from music_assistant_models.errors import (
    LoginFailed, ResourceTemporarilyUnavailable, RetriesExhausted,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ma'))
from maintain_ma_optimizations import optimized_source


def load_manager():
    source = optimized_source('providers/apple_music/media.py')
    tree = ast.parse(source)
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AppleMusicMediaManager')
    names = {'_get_playlist_ratings', '_get_playlist_tracks_cached'}
    methods = [n for n in original.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
    assert len(methods) == len(names)
    for method in methods:
        method.decorator_list = []
    cls = ast.ClassDef(name='Manager', bases=[], keywords=[], body=methods, decorator_list=[])
    env = dict(asyncio=asyncio, os=os, MediaType=MediaType, Track=NS,
               ResourceTemporarilyUnavailable=ResourceTemporarilyUnavailable,
               RetriesExhausted=RetriesExhausted, is_catalog_id=lambda value: value.startswith('pl.'),
               parse_track=lambda provider, item, favorite: NS(item_id=item['id'], favorite=favorite))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<actual-ma-media>', 'exec'), env)
    return env['Manager']


class PlaylistRatingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = load_manager()()
        self.manager.provider = NS(_storefront='cn')
        self.manager.logger = logging.getLogger('playlist-ratings-test')
        self.calls = []
        self.ids = [str(i) for i in range(98)]
        self.ratings = {'0': True, '1': False}
        self.error = None
        self.wait = False
        self.cancelled = asyncio.Event()
        self.entered = asyncio.Event()

        async def get_data(endpoint, **kwargs):
            self.calls.append((endpoint, kwargs))
            return {'data': [{'id': value} for value in self.ids]}

        async def get_ratings(ids, media_type):
            self.calls.append(('ratings', (ids, media_type)))
            self.entered.set()
            if self.wait:
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled.set()
            if self.error:
                raise self.error
            return self.ratings

        self.manager.api = NS(get_data=get_data, get_ratings=get_ratings)

    async def test_success_preserves_ratings_order_and_page_positions(self):
        tracks = await self.manager._get_playlist_tracks_cached('pl.test', 1)
        self.assertEqual(len(tracks), 98)
        self.assertTrue(tracks[0].favorite)
        self.assertFalse(tracks[1].favorite)
        self.assertEqual([t.item_id for t in tracks], self.ids)
        self.assertEqual([t.position for t in tracks], list(range(101, 199)))
        self.assertEqual(self.calls[0][1]['offset'], 100)

    async def test_timeout_returns_fetched_tracks_and_cancels_optional_request(self):
        self.wait = True
        with patch.dict(os.environ, R1_APPLE_PLAYLIST_RATINGS_TIMEOUT='0.02'):
            tracks = await asyncio.wait_for(self.manager._get_playlist_tracks_cached('pl.test'), .5)
        self.assertEqual(len(tracks), 98)
        self.assertTrue(self.cancelled.is_set())
        self.assertEqual(len(self.calls), 2)

    async def test_external_cancel_propagates_and_does_not_return_success(self):
        self.wait = True
        task = asyncio.create_task(self.manager._get_playlist_tracks_cached('pl.test'))
        await self.entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.cancelled.is_set())

    async def test_authentication_errors_remain_visible(self):
        self.error = LoginFailed('synthetic authorization failure')
        with self.assertRaises(LoginFailed):
            await self.manager._get_playlist_tracks_cached('pl.test')

    async def test_rate_or_transport_exhaustion_only_drops_optional_display(self):
        for error in (ResourceTemporarilyUnavailable('synthetic'), RetriesExhausted('synthetic')):
            self.error = error
            tracks = await self.manager._get_playlist_tracks_cached('pl.test')
            self.assertEqual(len(tracks), 98)

    async def test_track_request_failure_is_not_swallowed(self):
        async def failed(*args, **kwargs):
            raise ResourceTemporarilyUnavailable('synthetic tracks failure')
        self.manager.api.get_data = failed
        with self.assertRaises(ResourceTemporarilyUnavailable):
            await self.manager._get_playlist_tracks_cached('pl.test')
        self.assertFalse(self.entered.is_set())

    async def test_zero_disables_only_optional_lookup_and_library_playlist_keeps_endpoint(self):
        with patch.dict(os.environ, R1_APPLE_PLAYLIST_RATINGS_TIMEOUT='0'):
            tracks = await self.manager._get_playlist_tracks_cached('p.library')
        self.assertEqual(len(tracks), 98)
        self.assertEqual(self.calls[0][0], 'me/library/playlists/p.library/tracks')
        self.assertFalse(self.entered.is_set())

    async def test_empty_page_does_not_query_ratings(self):
        self.ids = []
        self.assertEqual(await self.manager._get_playlist_tracks_cached('pl.test'), [])
        self.assertFalse(self.entered.is_set())

    async def test_invalid_budget_uses_safe_default(self):
        for value in ('bad', '-1', 'nan', 'inf', '1000'):
            with patch.dict(os.environ, R1_APPLE_PLAYLIST_RATINGS_TIMEOUT=value):
                self.assertEqual(await self.manager._get_playlist_ratings(['0']), self.ratings)


if __name__ == '__main__':
    unittest.main()
