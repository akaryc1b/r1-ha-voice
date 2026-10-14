"""Exercise the real loader methods with isolated models and gated async I/O."""
from __future__ import annotations

import ast
import asyncio
import contextvars
import json
import os
import sys
import time
import unittest
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import SimpleNamespace as NS
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ma'))
from maintain_ma_optimizations import optimized_source
TARGET = Path('controllers/player_queues/queue_loader.py')


class MediaType(str, Enum):
    TRACK = 'track'
    AUDIO_SOURCE = 'audio_source'


class ContentType(str, Enum):
    AAC = 'aac'
    UNKNOWN = '?'


class PlaybackState(str, Enum):
    PLAYING = 'playing'
    PAUSED = 'paused'
    IDLE = 'idle'


class RepeatMode(str, Enum):
    OFF = 'off'
    ONE = 'one'
    ALL = 'all'


class EventType(str, Enum):
    QUEUE_UPDATED = 'queue_updated'
    QUEUE_ITEMS_UPDATED = 'queue_items_updated'


class MusicAssistantError(Exception):
    pass


class MediaNotFoundError(MusicAssistantError):
    pass


class ResourceTemporarilyUnavailable(MusicAssistantError):
    pass


class RetriesExhausted(MusicAssistantError):
    pass


class UniqueList(list):
    def __init__(self, values=()):
        super().__init__()
        self.extend(values)

    def append(self, value):
        if value not in self:
            super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


@dataclass(eq=False)
class Track:
    item_id: str = 'track1'
    name: str = 'Original track'
    provider: str = 'apple_music'
    duration: int | None = 240
    provider_mappings: list = field(default_factory=list)
    metadata: object = field(default_factory=lambda: NS(images=[]))
    album: object = None
    media_type: MediaType = MediaType.TRACK

    @property
    def image(self):
        return (getattr(self.album, 'image', None) or
                (self.metadata.images[0] if self.metadata.images else None))

    @property
    def uri(self):
        return f'{self.provider}://track/{self.item_id}'


class QueueItem:
    def __init__(self, item=None, queue_id='upbac50e55', item_id='queue-item1'):
        self.queue_id = queue_id
        self.queue_item_id = item_id
        self.media_item = item or make_track()
        self.available = True
        self.image = None
        self.streamdetails = None
        self.duration = self.media_item.duration

    @property
    def uri(self):
        return self.media_item.uri


def make_track(item_id='track1', images=()):
    audio = NS(content_type=ContentType.AAC, codec_type=ContentType.UNKNOWN,
               sample_rate=44100, bit_depth=16, channels=2)
    mapping = NS(provider_domain='apple_music', provider_instance='apple_music--test',
                 item_id=item_id, available=True, audio_format=audio)
    return Track(item_id=item_id, provider_mappings=[mapping],
                 metadata=NS(images=list(images)))


def compare_item_ids(left, right):
    return bool({(x.provider_instance, x.item_id) for x in left.provider_mappings} &
                {(x.provider_instance, x.item_id) for x in right.provider_mappings})


BYPASS_THROTTLER = contextvars.ContextVar('bypass', default=False)


class AsyncProxy:
    Event = asyncio.Event
    TimeoutError = asyncio.TimeoutError
    current_task = staticmethod(asyncio.current_task)
    timeout_override = None

    async def wait_for(self, coro, timeout):
        return await asyncio.wait_for(coro, self.timeout_override or timeout)


ASYNC = AsyncProxy()
module = ast.parse(optimized_source(TARGET.as_posix()))
setting = next(x for x in module.body if isinstance(x, ast.Assign) and
               any(isinstance(t, ast.Name) and t.id == 'R1_MA_QUEUE_ID' for t in x.targets))
exec(compile(ast.Module(body=[setting], type_ignores=[]), str(TARGET), 'exec'), globals())
source_class = next(x for x in module.body if isinstance(x, ast.ClassDef) and x.name == 'QueueLoaderMixin')
methods = [x for x in source_class.body if getattr(x, 'name', '') in
           ('_load_item', '_can_defer_r1_artwork', '_refresh_r1_artwork')]
isolated = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
                           ast.ClassDef(name='RealLoader', bases=[], keywords=[], body=methods, decorator_list=[])],
                      type_ignores=[])
ast.fix_missing_locations(isolated)
namespace = dict(globals(), asyncio=ASYNC)
exec(compile(isolated, str(TARGET), 'exec'), namespace)
RealLoader = namespace['RealLoader']


class Mass:
    def __init__(self):
        self.tasks = {}
        self.listeners = []
        self.cancelled_ids = []
        self.task_options = []

    def create_task(self, target, *args, task_id=None, abort_existing=False, eager_start=True):
        if abort_existing:
            self.cancel_task(task_id)
        task = asyncio.create_task(target(*args))
        self.tasks[task_id] = task
        self.task_options.append((task_id, eager_start))
        return task

    def cancel_task(self, task_id):
        self.cancelled_ids.append(task_id)
        if task_id in self.tasks:
            self.tasks[task_id].cancel()

    def subscribe(self, callback, events, queue_id):
        entry = (callback, events, queue_id)
        self.listeners.append(entry)
        return lambda: self.listeners.remove(entry)

    def emit(self, queue_id, event=EventType.QUEUE_UPDATED):
        for callback, events, target in list(self.listeners):
            if event in events and target == queue_id:
                callback(NS(event=event, object_id=queue_id))


class Host(RealLoader):
    def __init__(self, queue_item=None):
        self.item = queue_item or QueueItem()
        q = NS(display_name='Test', state=PlaybackState.IDLE, current_item=self.item, repeat_mode=RepeatMode.OFF)
        self.data = NS(queue=q, session_id='session1', items=[self.item])
        self._queue_data = {self.item.queue_id: self.data}
        self.mass = Mass()
        self.events = []
        self.fetch_started = asyncio.Event()
        self.fetch_release = None
        self.fetch_cancelled = False
        self.fetch_bypass = None
        self.fetch_error = None
        self.fetched = make_track(images=['remote-cover'])
        self.library = None
        self.album_library = None
        self.details_error = None
        self.details_media_type = MediaType.TRACK
        self.buffer_error = None
        self.buffer_release = None
        self.buffer_started = asyncio.Event()
        self.log = []
        self.logger = NS(debug=lambda *a:self.log.append(a), info=lambda *a:None, warning=lambda *a:self.log.append(a))
        self.mass.music = NS(get_library_item_by_prov_id=self.library_lookup,
                             get_item_by_uri=self.fetch)
        self.mass.streams = NS(audio=NS(get_stream_details=self.details,
                                       get_audio_buffer=self.buffer))

    async def library_lookup(self, media_type, item_id, provider):
        self.events.append('library')
        return self.album_library if media_type == 'album' else self.library

    async def fetch(self, uri):
        self.events.append('fetch')
        self.fetch_started.set()
        self.fetch_bypass = BYPASS_THROTTLER.get()
        try:
            if self.fetch_release:
                await self.fetch_release.wait()
            if self.fetch_error:
                raise self.fetch_error
            return self.fetched
        except asyncio.CancelledError:
            self.fetch_cancelled = True
            raise

    async def details(self, **kwargs):
        self.events.append('details')
        self.details_item = kwargs['queue_item'].media_item
        self.details_bypass = BYPASS_THROTTLER.get()
        if self.details_error:
            raise self.details_error
        return NS(media_type=self.details_media_type, duration=240)

    async def buffer(self, *args, **kwargs):
        self.events.append('buffer')
        self.buffer_started.set()
        if self.buffer_release:
            await self.buffer_release.wait()
        if self.buffer_error:
            raise self.buffer_error
        self.events.append('buffer_ready')

    async def _abort_superseded_source_buffers(self, item):
        self.events.append('abort_old_audio')

    def _apply_probed_duration(self, item):
        pass

    def _plays_as_album_track(self, item):
        return False

    def get_item(self, queue_id, item_id):
        data = self._queue_data.get(queue_id)
        return next((x for x in data.items if x.queue_item_id == item_id), None) if data else None

    def signal_update(self, queue_id, items_changed=False):
        self.events.append('images_updated')
        self.mass.emit(queue_id, EventType.QUEUE_ITEMS_UPDATED if items_changed else EventType.QUEUE_UPDATED)

    def playing(self):
        self.data.queue.current_item = self.item
        self.data.queue.state = PlaybackState.PLAYING
        self.mass.emit(self.item.queue_id)

    def task(self):
        return self.mass.tasks.get(f'r1_artwork_{self.item.queue_id}')


class ArtworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        ASYNC.timeout_override = None
        remaining = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)

    async def start_artwork(self, host):
        host.fetch_release = asyncio.Event()
        await host._load_item(host.item, is_start=True)
        host.playing()
        await asyncio.wait_for(host.fetch_started.wait(), .2)

    async def test_blocked_artwork_is_off_critical_path_and_only_images_change(self):
        h = Host()
        original = h.item.media_item
        maps = original.provider_mappings
        album = original.album
        h.fetch_release = asyncio.Event()
        h.fetched.name = 'Different metadata title'
        h.fetched.duration = 999
        h.fetched.provider_mappings.append(make_track('extra').provider_mappings[0])
        await asyncio.wait_for(h._load_item(h.item, is_start=True), .2)
        self.assertEqual(h.events, ['library', 'abort_old_audio', 'details', 'buffer', 'buffer_ready'])
        await asyncio.sleep(0)
        self.assertFalse(h.fetch_started.is_set())
        h.playing()
        await asyncio.wait_for(h.fetch_started.wait(), .2)
        self.assertTrue(h.details_bypass)
        self.assertFalse(h.fetch_bypass)
        self.assertEqual(h.mass.task_options[0][1], False)
        h.fetch_release.set()
        await h.task()
        self.assertIs(h.item.media_item, original)
        self.assertIs(original.provider_mappings, maps)
        self.assertIs(original.album, album)
        self.assertEqual((original.name, original.duration), ('Original track', 240))
        self.assertEqual(original.metadata.images, ['remote-cover'])
        self.assertEqual(h.item.image, 'remote-cover')
        self.assertFalse(h.mass.listeners)

    async def test_never_schedule_before_buffer_ready(self):
        h = Host()
        h.buffer_release = asyncio.Event()
        loading = asyncio.create_task(h._load_item(h.item, is_start=True))
        await h.buffer_started.wait()
        self.assertFalse(h.mass.tasks)
        self.assertFalse(h.fetch_started.is_set())
        h.buffer_release.set()
        await loading
        self.assertIsNotNone(h.task())

    async def test_library_quality_preference_preserved(self):
        h = Host()
        h.library = make_track(images=['library-cover'])
        h.library.provider_mappings.append(make_track('lossless').provider_mappings[0])
        await h._load_item(h.item, is_start=True)
        self.assertIs(h.details_item, h.library)
        self.assertEqual(len(h.item.media_item.provider_mappings), 2)
        self.assertFalse(h.fetch_started.is_set())
        self.assertFalse(h.mass.tasks)

    async def test_resolved_album_art_avoids_background_fetch(self):
        h = Host()
        h.item.media_item.album = NS(media_type='album', item_id='album1', provider='apple_music', image=None)
        h.album_library = NS(image='album-cover')
        await h._load_item(h.item, is_start=True)
        self.assertEqual(h.item.media_item.image, 'album-cover')
        self.assertFalse(h.mass.tasks)

    async def test_album_mapping_image_needs_no_provider_fetch(self):
        h = Host()
        h.item.media_item.album = NS(media_type='album', item_id='album1', provider='apple_music', image='mapped-cover')
        await h._load_item(h.item, is_start=True)
        self.assertEqual(h.item.media_item.metadata.images, ['mapped-cover'])
        self.assertFalse(h.fetch_started.is_set())
        self.assertFalse(h.mass.tasks)

    async def test_configured_queue_only_can_defer_artwork(self):
        method = RealLoader._can_defer_r1_artwork
        original = method.__globals__['R1_MA_QUEUE_ID']
        try:
            method.__globals__['R1_MA_QUEUE_ID'] = 'custom-bedroom'
            item = QueueItem(queue_id='custom-bedroom')
            self.assertTrue(method(item, True))
            item.queue_id = 'upbac50e55'
            self.assertFalse(method(item, True))
        finally:
            method.__globals__['R1_MA_QUEUE_ID'] = original

    async def test_noneligible_listings_keep_full_lookup(self):
        mutations = {
            'other_player': lambda q:setattr(q, 'queue_id', 'other'),
            'missing_duration': lambda q:setattr(q.media_item, 'duration', None),
            'zero_duration': lambda q:setattr(q.media_item, 'duration', 0),
            'no_mappings': lambda q:setattr(q.media_item, 'provider_mappings', []),
            'multiple_providers': lambda q:q.media_item.provider_mappings.append(make_track('two').provider_mappings[0]),
            'unavailable_mapping': lambda q:setattr(q.media_item.provider_mappings[0], 'available', False),
            'unknown_format': lambda q:setattr(q.media_item.provider_mappings[0].audio_format, 'content_type', ContentType.UNKNOWN),
            'different_rate': lambda q:setattr(q.media_item.provider_mappings[0].audio_format, 'sample_rate', 48000),
            'different_depth': lambda q:setattr(q.media_item.provider_mappings[0].audio_format, 'bit_depth', 24),
            'different_channels': lambda q:setattr(q.media_item.provider_mappings[0].audio_format, 'channels', 1),
            'different_item_id': lambda q:setattr(q.media_item.provider_mappings[0], 'item_id', 'different'),
            'missing_provider_instance': lambda q:setattr(q.media_item.provider_mappings[0], 'provider_instance', ''),
            'different_provider_domain': lambda q:setattr(q.media_item.provider_mappings[0], 'provider_domain', 'ytmusic'),
            'ytmusic': lambda q:setattr(q.media_item, 'provider', 'ytmusic--test'),
            'unknown_provider': lambda q:setattr(q.media_item, 'provider', 'library'),
            'missing_name': lambda q:setattr(q.media_item, 'name', ''),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                q = QueueItem()
                mutate(q)
                h = Host(q)
                await h._load_item(q, is_start=True)
                self.assertLess(h.events.index('fetch'), h.events.index('details'))
                self.assertIs(h.details_item, h.fetched)
                self.assertFalse(h.mass.tasks)

    async def test_preloading_still_fetches_full_metadata(self):
        h = Host()
        await h._load_item(h.item, is_start=False)
        self.assertLess(h.events.index('fetch'), h.events.index('details'))
        self.assertNotIn('buffer', h.events)
        self.assertFalse(h.mass.tasks)

    async def test_repeat_one_reuses_existing_preload_without_duplicate_lookup(self):
        h = Host()
        h.data.queue.repeat_mode = RepeatMode.ONE
        await h._load_item(h.item, is_start=True)
        self.assertFalse(h.fetch_started.is_set())
        self.assertFalse(h.mass.tasks)
        await h._load_item(h.item, is_start=False)
        self.assertEqual(h.events.count('fetch'), 1)
        self.assertIs(h.item.media_item, h.fetched)

    async def test_real_stream_and_buffer_errors_propagate(self):
        for stage in ('details_error', 'buffer_error'):
            with self.subTest(stage=stage):
                h = Host()
                error = MediaNotFoundError('actual playback failed')
                setattr(h, stage, error)
                with self.assertRaises(MediaNotFoundError) as caught:
                    await h._load_item(h.item, is_start=True)
                self.assertIs(caught.exception, error)
                self.assertFalse(h.mass.tasks)

    async def test_unavailable_queue_item_error_propagates(self):
        h = Host()
        h.item.available = False
        with self.assertRaises(MediaNotFoundError):
            await h._load_item(h.item, is_start=True)
        self.assertFalse(h.fetch_started.is_set())

    async def test_audio_source_without_buffer_does_not_schedule_artwork(self):
        h = Host()
        h.details_media_type = MediaType.AUDIO_SOURCE
        await h._load_item(h.item, is_start=True)
        self.assertNotIn('buffer', h.events)
        self.assertFalse(h.mass.tasks)

    async def test_stop_session_switch_item_replace_cancel_inflight_fetch(self):
        for mutation in ('stop', 'session', 'current_item', 'queue_replace', 'item_remove', 'media_replace', 'repeat_one'):
            with self.subTest(mutation=mutation):
                h = Host()
                old = h.item.media_item
                await self.start_artwork(h)
                if mutation == 'stop': h.data.queue.state = PlaybackState.IDLE
                elif mutation == 'session': h.data.session_id = 'session2'
                elif mutation == 'current_item': h.data.queue.current_item = QueueItem(item_id='new')
                elif mutation == 'queue_replace': h._queue_data[h.item.queue_id] = NS(queue=h.data.queue, session_id='session1', items=[h.item])
                elif mutation == 'item_remove': h.data.items = []
                elif mutation == 'repeat_one': h.data.queue.repeat_mode = RepeatMode.ONE
                else: h.item.media_item = make_track()
                h.mass.emit(h.item.queue_id)
                await asyncio.gather(h.task(), return_exceptions=True)
                self.assertTrue(h.fetch_cancelled)
                self.assertEqual(old.metadata.images, [])
                self.assertFalse(h.mass.listeners)

    async def test_stale_completion_without_event_cannot_mutate(self):
        h = Host()
        await self.start_artwork(h)
        h.data.session_id = None
        h.fetch_release.set()
        await h.task()
        self.assertEqual(h.item.media_item.metadata.images, [])

    async def test_new_load_cancels_previous_artwork_task(self):
        h = Host()
        await self.start_artwork(h)
        old_task = h.task()
        replacement = QueueItem(make_track('new', ['existing']), item_id='new-queue-item')
        h.data.items.append(replacement)
        await h._load_item(replacement, is_start=True)
        await asyncio.gather(old_task, return_exceptions=True)
        self.assertTrue(old_task.cancelled())
        self.assertTrue(h.fetch_cancelled)
        self.assertFalse(h.mass.listeners)

    async def test_external_task_cancellation_cleans_subscription_and_request(self):
        h = Host()
        await self.start_artwork(h)
        h.mass.cancel_task(f'r1_artwork_{h.item.queue_id}')
        await asyncio.gather(h.task(), return_exceptions=True)
        self.assertTrue(h.fetch_cancelled)
        self.assertFalse(h.mass.listeners)

    async def test_artwork_error_is_optional_and_does_not_mutate_playback(self):
        h = Host()
        h.fetch_error = MediaNotFoundError('optional metadata missing')
        await h._load_item(h.item, is_start=True)
        h.playing()
        await h.task()
        self.assertEqual(h.data.queue.state, PlaybackState.PLAYING)
        self.assertEqual(h.item.media_item.metadata.images, [])
        self.assertFalse(h.mass.listeners)

    async def test_bounded_request_timeout_cancels_fetch(self):
        h = Host()
        ASYNC.timeout_override = .02
        await self.start_artwork(h)
        await h.task()
        self.assertTrue(h.fetch_cancelled)
        self.assertFalse(h.mass.listeners)

    async def test_never_playing_timeout_issues_no_metadata_request(self):
        h = Host()
        ASYNC.timeout_override = .02
        await h._load_item(h.item, is_start=True)
        await h.task()
        self.assertFalse(h.fetch_started.is_set())
        self.assertFalse(h.mass.listeners)

    async def test_wrong_track_or_nontrack_result_cannot_add_artwork(self):
        for value in (make_track('other', ['wrong-cover']), NS(image='wrong-cover')):
            with self.subTest(value=type(value).__name__):
                h = Host()
                h.fetched = value
                await h._load_item(h.item, is_start=True)
                h.playing()
                await h.task()
                self.assertEqual(h.item.media_item.metadata.images, [])

    async def test_images_added_during_fetch_and_queue_image_are_preserved(self):
        h = Host()
        h.item.image = 'existing-queue-cover'
        await self.start_artwork(h)
        h.item.media_item.metadata.images.append('existing-track-cover')
        h.fetch_release.set()
        await h.task()
        self.assertEqual(h.item.media_item.metadata.images, ['existing-track-cover', 'remote-cover'])
        self.assertEqual(h.item.image, 'existing-queue-cover')

    async def test_no_image_response_does_not_emit_update(self):
        h = Host()
        h.fetched = make_track()
        await h._load_item(h.item, is_start=True)
        h.playing()
        await h.task()
        self.assertNotIn('images_updated', h.events)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArtworkTests))
    report = {'tests_run': result.testsRun, 'failures': len(result.failures),
              'errors': len(result.errors), 'successful': result.wasSuccessful(),
              'scope': 'isolated real loader methods; no device playback, production writes or network calls'}
    (Path(__file__).parent / 'test-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
