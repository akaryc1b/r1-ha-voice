"""从统一补丁提取真实读取器，验证字节续传与取消边界。"""
import ast
import asyncio
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import aiohttp
from aiohttp import ClientTimeout
from yarl import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ma"))
from maintain_ma_optimizations import optimized_source

class AudioError(Exception):
    pass

tree = ast.parse(optimized_source("controllers/streams/audio.py"))
method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_get_r1_apple_http_stream")
namespace = dict(aiohttp=aiohttp, ClientTimeout=ClientTimeout, AudioError=AudioError,
                 re=re, encoded_request_url=lambda value: URL(value, encoded=True))
method.returns = None
exec(compile(ast.Module(body=[method], type_ignores=[]), "actual_http_pipe", "exec"), namespace)
stream = namespace[method.name]

class Response:
    def __init__(self, status=200, chunks=(), headers=None):
        self.status, self.chunks, self.headers = status, chunks, headers or {}
        self.closed = False
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

class HttpPipeTests(unittest.IsolatedAsyncioTestCase):
    def host(self, *responses):
        return SimpleNamespace(mass=SimpleNamespace(http_session=SimpleNamespace(
            get=Mock(side_effect=responses))), logger=Mock())

    async def collect(self, host):
        return b"".join([chunk async for chunk in stream(host, "https://example.test/a%2Fb?sig=x%2Fy")])

    async def test_original_bytes_and_encoded_url_are_preserved(self):
        response = Response(chunks=[b"\x00\xff", b"\x80abc"])
        host = self.host(response)
        self.assertEqual(await self.collect(host), b"\x00\xff\x80abc")
        args, kwargs = host.mass.http_session.get.call_args
        self.assertEqual(str(args[0]), "https://example.test/a%2Fb?sig=x%2Fy")
        self.assertFalse(kwargs["auto_decompress"])
        self.assertIsNone(kwargs["timeout"].total)
        self.assertTrue(response.closed)

    async def test_disconnect_resumes_at_exact_delivered_byte_with_validator(self):
        first = Response(chunks=[b"abc", aiohttp.ClientPayloadError()], headers={"ETag": '"same"'})
        second = Response(206, [b"def"], {"Content-Range": "bytes 3-5/6"})
        host = self.host(first, second)
        self.assertEqual(await self.collect(host), b"abcdef")
        self.assertEqual(host.mass.http_session.get.call_args.kwargs["headers"]["Range"], "bytes=3-")
        self.assertEqual(host.mass.http_session.get.call_args.kwargs["headers"]["If-Range"], '"same"')
        self.assertTrue(first.closed and second.closed)

    async def test_wrong_or_missing_resume_range_fails_without_replaying(self):
        for headers in ({}, {"Content-Range": "bytes 0-5/6"}):
            host = self.host(Response(chunks=[b"abc", TimeoutError()]), Response(206, [b"abcdef"], headers))
            with self.assertRaisesRegex(AudioError, "range mismatch"):
                await self.collect(host)

    async def test_ignored_range_or_changed_resource_is_rejected(self):
        host = self.host(Response(chunks=[b"abc", TimeoutError()]), Response(200, [b"abcdef"]))
        with self.assertRaisesRegex(AudioError, "HTTP status 200"):
            await self.collect(host)

    async def test_authorization_failure_does_not_retry_or_expose_url(self):
        host = self.host(Response(403))
        with self.assertRaisesRegex(AudioError, "Apple audio HTTP status 403"):
            await self.collect(host)
        self.assertEqual(host.mass.http_session.get.call_count, 1)

    async def test_connection_retries_are_bounded_and_error_hides_private_url(self):
        host = self.host(*[Response(chunks=[aiohttp.ClientConnectionError("private-url")]) for _ in range(3)])
        with self.assertRaises(AudioError) as caught:
            await self.collect(host)
        self.assertNotIn("private-url", str(caught.exception))
        self.assertEqual(host.mass.http_session.get.call_count, 3)

    async def test_cancel_closes_response_and_never_retries(self):
        response = Response(chunks=[asyncio.CancelledError()])
        host = self.host(response)
        with self.assertRaises(asyncio.CancelledError):
            await self.collect(host)
        self.assertTrue(response.closed)
        self.assertEqual(host.mass.http_session.get.call_count, 1)

    async def test_consumer_close_releases_http_response(self):
        response = Response(chunks=[b"abc", b"def"])
        host = self.host(response)
        generator = stream(host, "https://example.test/audio")
        self.assertEqual(await anext(generator), b"abc")
        await generator.aclose()
        self.assertTrue(response.closed)

if __name__ == "__main__":
    unittest.main()
