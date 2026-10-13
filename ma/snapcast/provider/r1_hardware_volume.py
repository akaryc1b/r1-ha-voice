"""Optional direct hardware volume for an R1 Snapcast output.

The Snapcast software gain stays at unity; only Android STREAM_MUSIC is changed.
An empty URL keeps the normal Snapcast client behavior.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout

CONF_R1_HARDWARE_VOLUME_URL = "r1_hardware_volume_url"


class R1HardwareVolume:
    """Read actual device steps and preserve hardware mute restoration."""

    def __init__(self, session: ClientSession, url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/voice_volume"
        ):
            raise ValueError("Use the R1 /voice_volume endpoint without credentials or query")
        self.session = session
        self.url = url
        self.percent: int | None = None
        self.muted = False
        self._lock = asyncio.Lock()

    async def request(self, operation: str = "get", percent: int = 0) -> tuple[int, bool]:
        if operation not in ("get", "set", "mute", "unmute"):
            raise ValueError("Invalid R1 music volume operation")
        if not 0 <= percent <= 100:
            raise ValueError("Invalid R1 music volume percent")
        async with self._lock:
            async with self.session.get(
                self.url,
                params={"target": "music", "operation": operation, "percent": percent},
                timeout=ClientTimeout(total=1.0),
            ) as response:
                response.raise_for_status()
                result = await response.json()
            value = result.get("percent")
            if result.get("target") != "music" or type(value) is not int or not 0 <= value <= 100:
                raise ValueError("Invalid R1 music volume response")
            self.percent = value
            self.muted = value == 0
            return self.percent, self.muted
