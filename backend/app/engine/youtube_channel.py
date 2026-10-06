"""Stream YouTube channel entries into the download queue without blocking HTTP."""

import asyncio
import queue
import re
import threading
import time
import uuid

import yt_dlp

from app.engine.youtube_support import youtube_cookie_fallback, youtube_auth_message, YouTubeAuthenticationError
from app.core.logger import get_media_logger


def channel_entries(url, stopped):
    # process=False keeps playlist generators lazy, including nested channel tabs.
    # Processing the result normally enumerates the entire channel before returning.
    options = {
        "logger": get_media_logger(url),
        "ignoreconfig": True, "extract_flat": True, "skip_download": True,
        "quiet": True, "no_warnings": True, "socket_timeout": 10,
        "retries": 1, "extractor_retries": 1,
    }
    visited = set()
    video_ids = set()
    def collect(cookie_file):
        with yt_dlp.YoutubeDL({**options, **({"cookiefile": cookie_file} if cookie_file else {})}) as ydl:
            def walk(info):
                if stopped.is_set() or not info:
                    return
                if info.get("entries") is not None:
                    for entry in info["entries"]:
                        if stopped.is_set():
                            return
                        yield from walk(entry)
                    return
                video_id = str(info.get("id") or "")
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    if video_id not in video_ids and info.get("live_status") not in {"is_live", "is_upcoming"}:
                        video_ids.add(video_id)
                        yield {**info, "url": f"https://www.youtube.com/watch?v={video_id}"}
                    return
                target = info.get("url")
                if target and info.get("ie_key") == "YoutubeTab" and target not in visited:
                    visited.add(target)
                    yield from walk(ydl.extract_info(target, download=False, process=False))

            yield from walk(ydl.extract_info(url, download=False, process=False))

    try:
        yield from collect(None)
    except Exception as error:
        with youtube_cookie_fallback(error) as cookie_file:
            visited.clear()
            try:
                yield from collect(cookie_file)
            except Exception as authenticated_error:
                message = youtube_auth_message(authenticated_error, has_cookies=True)
                if message:
                    raise YouTubeAuthenticationError(message) from None
                raise


class ChannelImports:
    idle_timeout = 90
    total_timeout = 900

    def __init__(self, enqueue):
        self.enqueue = enqueue
        self.jobs = {}
        self.tasks = {}
        self.stops = {}
        self.slot = asyncio.Semaphore(1)

    def start(self, url, output_dir, quality):
        for job in self.jobs.values():
            if job["url"] == url and job["state"] in {"queued", "collecting"}:
                return dict(job)
        job = {"id": str(uuid.uuid4()), "url": url, "state": "queued",
               "added_count": 0, "skipped_count": 0, "error": None}
        self.jobs[job["id"]] = job
        task = asyncio.create_task(self._run(job, output_dir, quality))
        self.tasks[job["id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(job["id"], None))
        return dict(job)

    def list(self):
        return [dict(job) for job in self.jobs.values()]

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError("채널 수집 작업을 찾을 수 없습니다.")
        task = self.tasks.get(job_id)
        if task and not task.done():
            job["state"] = "cancelled"
            stop = self.stops.get(job_id)
            if stop:
                stop.set()
            task.cancel()
        else:
            self.jobs.pop(job_id, None)
        return {"id": job_id, "state": job["state"]}

    async def _run(self, job, output_dir, quality):
        stopped = threading.Event()
        self.stops[job["id"]] = stopped
        items = queue.Queue(maxsize=64)

        def send(item):
            while not stopped.is_set():
                try:
                    items.put(item, timeout=0.2)
                    return
                except queue.Full:
                    pass

        def collect():
            try:
                for entry in channel_entries(job["url"], stopped):
                    if stopped.is_set():
                        return
                    send(entry)
            except Exception as exc:
                send(exc)
            finally:
                send(None)

        try:
            async with self.slot:
                job["state"] = "collecting"
                worker = asyncio.create_task(asyncio.to_thread(collect))
                # Keep a reference until the worker finishes after cancellation.
                worker.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
                started = last_entry = time.monotonic()
                while True:
                    if time.monotonic() - started > self.total_timeout:
                        raise TimeoutError("채널 수집 제한 시간을 초과했습니다. 이미 추가한 영상은 유지됩니다.")
                    try:
                        entry = items.get_nowait()
                    except queue.Empty:
                        now = time.monotonic()
                        if now - last_entry > self.idle_timeout:
                            raise TimeoutError("채널 응답이 지연되어 수집을 중단했습니다. 이미 추가한 영상은 유지됩니다.")
                        await asyncio.sleep(0.05)
                        continue
                    last_entry = time.monotonic()
                    if isinstance(entry, Exception):
                        raise entry
                    if entry is None:
                        if not job["added_count"] and not job["skipped_count"]:
                            raise ValueError("채널에서 다운로드할 수 있는 영상을 찾지 못했습니다.")
                        job["state"] = "completed"
                        break
                    added = await self.enqueue(entry, output_dir, quality)
                    job["added_count" if added else "skipped_count"] += 1
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            job["state"] = "cancelled"
            raise
        except Exception as exc:
            job["state"] = "error"
            job["error"] = str(exc)
        finally:
            stopped.set()
            self.stops.pop(job["id"], None)
