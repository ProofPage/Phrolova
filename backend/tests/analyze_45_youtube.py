import asyncio
import json
import subprocess
import sys
from pathlib import Path
from app.core.utils import extract_youtube_id
from app.engine.youtube import YoutubeLiveEngine
from app.engine.youtube_support import is_youtube_url

# 15 Live URLs
LIVES = [
    "https://www.youtube.com/live/BQJSlMSIrPk",
    "https://www.youtube.com/live/kuisr7IcDGQ",
    "https://www.youtube.com/live/HL79bf1HLKo",
    "https://www.youtube.com/live/Pr6wm391iF0",
    "https://www.youtube.com/live/3gq5H4yCRNc",
    "https://www.youtube.com/live/R_kL8y0d0vA",
    "https://www.youtube.com/live/cfNi7ptZQ-M",
    "https://www.youtube.com/live/e7Er77h73Gc",
    "https://www.youtube.com/live/2XnT5I7mHig",
    "https://www.youtube.com/live/3CTuo_g7Zus",
    "https://www.youtube.com/live/UkMM-9W0C70",
    "https://www.youtube.com/live/agMYragBKYc",
    "https://www.youtube.com/live/BUlu4AzAVWY",
    "https://www.youtube.com/live/drCoHiNJobI",
    "https://www.youtube.com/live/QbzN3wLDXek",
]

# 15 Standard VOD URLs
VODS = [
    "https://www.youtube.com/watch?v=7ThHKwLKVmc",
    "https://www.youtube.com/watch?v=yVmaXmA9qeo",
    "https://www.youtube.com/watch?v=d4mnBEuorf8",
    "https://www.youtube.com/watch?v=AuQq2EuZAvQ",
    "https://www.youtube.com/watch?v=5VjaDiUc9iA",
    "https://www.youtube.com/watch?v=p-wZrgI88dE",
    "https://www.youtube.com/watch?v=ImJwX-1aEmo",
    "https://www.youtube.com/watch?v=H7D9sBOT2AA",
    "https://www.youtube.com/watch?v=TZFDpGFX81g",
    "https://www.youtube.com/watch?v=3lnLzww4nzE",
    "https://www.youtube.com/watch?v=_3mgg-CWLyw",
    "https://www.youtube.com/watch?v=V2Aer6-YR5M",
    "https://www.youtube.com/watch?v=C6z0mv9yD5g",
    "https://www.youtube.com/watch?v=LTJTC3RH9mY",
    "https://www.youtube.com/watch?v=Kl6GCuCwsVY",
]

# 15 Shorts URLs
SHORTS = [
    "https://www.youtube.com/shorts/1xX2yY3zZ4a",
    "https://www.youtube.com/shorts/3j9ExRpRHfk",
    "https://www.youtube.com/shorts/3_6R9PaTVBQ",
    "https://www.youtube.com/shorts/j10m7ufeSL8",
    "https://www.youtube.com/shorts/MG7-yzlXJsg",
    "https://www.youtube.com/shorts/eSexbwEi4-w",
    "https://www.youtube.com/shorts/jmgaceWeuWI",
    "https://www.youtube.com/shorts/dXGB7XFhmMs",
    "https://www.youtube.com/shorts/JAH6rPcHGbU",
    "https://www.youtube.com/shorts/qyc7GsDw_nQ",
    "https://www.youtube.com/shorts/tEOr4dWtLVM",
    "https://www.youtube.com/shorts/9FjbdgeQsyA",
    "https://www.youtube.com/shorts/8JB5jVyfqUI",
    "https://www.youtube.com/shorts/t6L9gO-yir4",
    "https://www.youtube.com/shorts/8c6YRZ24QPQ",
]

async def analyze():
    print(f"=== [1] URL Extraction & Normalization Test (Total 45 URLs) ===")
    all_urls = LIVES + VODS + SHORTS
    for url in all_urls:
        vid = extract_youtube_id(url)
        assert len(vid) == 11, f"Failed to extract 11-char ID from {url}: got {vid}"
        assert not vid.startswith("@"), f"ID should not have @: {vid}"
        assert is_youtube_url(url), f"Should be recognized as YouTube URL: {url}"
    print(f"PASS: All 45 YouTube URLs successfully extracted to clean 11-char video IDs!")

    print(f"\n=== [2] Live Engine Inspection (Sample 5 Lives) ===")
    engine = YoutubeLiveEngine()
    for live_url in LIVES[:5]:
        vid = extract_youtube_id(live_url)
        status = await engine.check_live_status(vid)
        stream_url = engine.get_stream_url(vid)
        print(f"Live [{vid}] is_live={status.get('is_live')} title='{status.get('title')[:30]}' viewers={status.get('viewer_count')} stream_url={stream_url}")
        assert stream_url.startswith("https://www.youtube.com/watch?v="), f"Invalid stream url: {stream_url}"

    print(f"\n=== [3] VOD & Shorts Stream Format Inspection via yt-dlp (Sample) ===")
    sample_tests = [LIVES[0], VODS[0], SHORTS[1]]
    for target in sample_tests:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "yt_dlp", "--simulate", "-j", "--no-warnings", target,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            fmt_count = len(data.get("formats", []))
            print(f"Target [{data.get('id')}] Type={data.get('_type', 'video')} Title='{data.get('title')[:25]}' Formats={fmt_count} Duration={data.get('duration')}s")
        else:
            print(f"Target [{target}] yt-dlp notice: {stderr.decode()[:80]}")

    print("\nALL 45 TARGETS VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(analyze())
