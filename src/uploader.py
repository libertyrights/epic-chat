import asyncio
import aiohttp
from pathlib import Path

UPLOAD_ENDPOINT = "https://0x0.st"


async def upload_file(path: str, endpoint: str = UPLOAD_ENDPOINT) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("File exceeds 512MB limit")

    async with aiohttp.ClientSession() as sess:
        with open(path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("file", f, filename=path.name)
            async with sess.post(endpoint, data=data) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Upload failed: HTTP {resp.status}")
                url = (await resp.text()).strip()
                return url
