"""Durable post-recording stream-copy jobs. Never operate on an open capture."""

from __future__ import annotations
import asyncio
import errno
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from app.core.config import get_settings
from app.core.logger import logger
from app.engine.media_inspection import probe_media
from app.engine.platform_auth import redact_media_error
from app.store.db import get_database


def now():
    return datetime.now().isoformat()


def publish_file(source: Path, target: Path):
    """Publish without overwriting, including filesystems without hard links."""
    try:
        os.link(source, target)
    except OSError as error:
        if error.errno not in (errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EACCES):
            raise
        created = False
        try:
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                created = True
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise
    source.unlink()


def recording_policy():
    rows = get_database().query(
        "SELECT value FROM app_settings WHERE key='recording_output'"
    )
    if rows:
        return json.loads(rows[0]["value"])
    settings = get_settings()
    # An explicitly saved old TS/MKV/MP4 preference is preserved. Fresh installs
    # use MP4; no existing recordings are rewritten by this migration.
    legacy = (
        settings.live_format
        if "live_format" in settings.model_fields_set
        and settings.live_format in ("ts", "mkv", "mp4")
        else "mp4"
    )
    if "live_format" not in settings.model_fields_set:
        from app.core.utils import _get_env_path

        # Older hand-written .env files could rely on the previous implicit TS default.
        if _get_env_path().is_file():
            legacy = "ts"
    return {"output_format": legacy, "keep_source_ts": True, "max_concurrent": 1}


def save_recording_policy(values):
    get_database().execute(
        "INSERT INTO app_settings(key,value) VALUES('recording_output',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(values),),
    )


class RecordingFinalizer:
    def __init__(self, on_change=None, on_finished=None):
        self.db = get_database()
        self.on_change = on_change
        self.on_finished = on_finished
        self._runner = None
        self._active = {}
        self._stopping = False
        self._owned_captures = set()
        self._recovered = False

    def list_jobs(self):
        return [
            json.loads(row["payload"])
            for row in self.db.query(
                "SELECT payload FROM recording_jobs ORDER BY updated_at DESC"
            )
        ]

    def get(self, job_id):
        rows = self.db.query("SELECT payload FROM recording_jobs WHERE id=?", (job_id,))
        if not rows:
            raise ValueError("변환 작업을 찾을 수 없습니다.")
        return json.loads(rows[0]["payload"])

    def _save(self, job):
        job["updated_at"] = now()
        self.db.execute(
            "INSERT INTO recording_jobs(id,composite_key,source_path,state,payload,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload=excluded.payload,updated_at=excluded.updated_at",
            (
                job["id"],
                job["composite_key"],
                job["source_path"],
                job["state"],
                json.dumps(job, ensure_ascii=False),
                job["updated_at"],
            ),
        )
        if self.on_change:
            self.on_change()

    def register_capture(self, key, pipeline, channel, policy):
        job = {
            "id": uuid.uuid4().hex,
            "composite_key": key,
            "platform": channel.platform.value,
            "channel_id": channel.channel_id,
            "channel_name": channel.channel_name or channel.channel_id,
            "state": "recording",
            "source_path": pipeline.output_path,
            "source_paths": list(pipeline._source_files),
            "output_path": None,
            "target_format": policy["output_format"],
            "keep_source_ts": policy["keep_source_ts"],
            "progress": None,
            "error_message": None,
            "diagnostics": {},
            "started_at": pipeline.get_status()["start_time"],
            "ended_at": None,
            "processing_started_at": None,
            "processing_completed_at": None,
            "inspection_state": "pending",
            "retry_count": 0,
            "writer_closed": False,
            "duration_seconds": 0,
            "file_size_bytes": 0,
        }
        self._owned_captures.add(job["id"])
        self._save(job)
        return job["id"]

    async def start(self, recover=False):
        if recover and not self._recovered:
            for job in self.list_jobs():
                if (
                    job["state"] in ("recording", "converting", "verifying")
                    and job["id"] not in self._owned_captures
                ):
                    job.update(
                        state="attention",
                        writer_closed=True,
                        error_message="작업이 중단되었습니다. 원본을 보관했습니다. 파일을 확인한 뒤 다시 변환하세요.",
                        progress=None,
                    )
                    self._save(job)
            self._recovered = True
        self._stopping = False
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._schedule())

    async def capture_finished(self, job_id, pipeline):
        if not pipeline._closed:
            raise RuntimeError("Streamlink 파일 쓰기가 아직 종료되지 않았습니다.")
        job = self.get(job_id)
        job.update(
            source_paths=list(pipeline._source_files),
            writer_closed=True,
            ended_at=now(),
            state="pending",
            end_reason=pipeline.end_reason,
            duration_seconds=pipeline.duration_seconds,
            file_size_bytes=pipeline.file_size_bytes,
        )
        if (
            not Path(job["source_paths"][0]).is_file()
            or Path(job["source_paths"][0]).stat().st_size == 0
        ):
            job.update(
                state="failed", error_message="녹화한 TS 파일이 없거나 비어 있습니다."
            )
        self._save(job)
        self.db.execute(
            "INSERT OR IGNORE INTO live_history(composite_key,platform,channel_id,channel_name,started_at,ended_at,duration_seconds,file_size_bytes,output_path,recording_job_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                job["composite_key"],
                job["platform"],
                job["channel_id"],
                job["channel_name"],
                job["started_at"],
                job["ended_at"],
                job["duration_seconds"],
                job["file_size_bytes"],
                job["source_paths"][0],
                job_id,
            ),
        )
        if not self._stopping:
            await self.start()

    async def retry(self, job_id, target_format=None, inspect_only=False):
        job = self.get(job_id)
        if job["state"] in ("recording", "pending", "converting", "verifying") or (
            job_id in self._active and not self._active[job_id].done()
        ):
            raise ValueError("현재 작업이 진행 중입니다.")
        if target_format:
            job["target_format"] = target_format
        if (
            inspect_only
            and job.get("output_path")
            and Path(job["output_path"]).is_file()
        ):
            job.update(state="verifying", inspection_state="running")
            self._save(job)
            try:
                media = await asyncio.to_thread(probe_media, job["output_path"])
                if (
                    "video" not in media["streams"]
                    or not media["duration"]
                    or media["diagnostics"]["stderr"].strip()
                ):
                    raise RuntimeError("파일 정보를 확인하지 못했습니다.")
                expected_format = {"mp4": "mp4", "mkv": "matroska", "ts": "mpegts"}[
                    job["target_format"]
                ]
                previous = job.get("inspection") or {}
                if expected_format not in media["format_name"]:
                    raise RuntimeError("선택한 형식과 파일 형식이 다릅니다.")
                if previous.get("tracks"):
                    fields = (
                        "codec_type",
                        "codec_name",
                        "width",
                        "height",
                        "avg_frame_rate",
                    )
                    if [[t.get(k) for k in fields] for t in previous["tracks"]] != [
                        [t.get(k) for k in fields] for t in media["tracks"]
                    ]:
                        raise RuntimeError("저장된 검사 결과와 스트림 정보가 다릅니다.")
                if previous.get("duration") and abs(
                    media["duration"] - previous["duration"]
                ) > max(2, previous["duration"] * 0.02):
                    raise RuntimeError("저장된 영상 길이와 다릅니다.")
                job.update(
                    state="completed", inspection_state="passed", error_message=None
                )
            except Exception as error:
                job.update(
                    state="attention",
                    inspection_state="failed",
                    error_message="파일 정보를 확인하지 못했습니다. 저장된 파일을 확인하세요.",
                )
                job["diagnostics"]["detail"] = redact_media_error(error)
            self._save(job)
            return job
        if not all(
            Path(p).is_file() and Path(p).stat().st_size > 0
            for p in job["source_paths"]
        ):
            raise ValueError("원본 파일을 찾을 수 없습니다. 저장 위치를 확인하세요.")
        if not inspect_only:
            job["previous_output_path"] = job.get("output_path")
            job["output_path"] = None
        job.update(
            state="pending",
            writer_closed=True,
            progress=None,
            error_message=None,
            inspection_state="pending",
            retry_count=job["retry_count"] + 1,
            inspect_only=inspect_only,
        )
        self._save(job)
        await self.start()
        return job

    async def _schedule(self):
        while not self._stopping:
            self._active = {
                key: task for key, task in self._active.items() if not task.done()
            }
            limit = recording_policy()["max_concurrent"]
            for job in self.list_jobs():
                if len(self._active) >= limit:
                    break
                if job["state"] == "pending" and job["id"] not in self._active:
                    self._active[job["id"]] = asyncio.create_task(
                        self._convert(job["id"])
                    )
            await asyncio.sleep(0.2)

    async def close(self):
        self._stopping = True
        if self._runner:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
        for task in self._active.values():
            task.cancel()
        await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._active.clear()

    def _claim(self, job_id):
        with self.db.transaction() as connection:
            return (
                connection.execute(
                    "UPDATE recording_jobs SET state='converting' WHERE id=? AND state='pending'",
                    (job_id,),
                ).rowcount
                == 1
            )

    async def _convert(self, job_id):
        if not self._claim(job_id):
            return
        job = self.get(job_id)
        proc = None
        stderr_task = None
        try:
            if not job["writer_closed"]:
                raise RuntimeError("녹화 종료 확인 후 변환할 수 있습니다.")
            sources = [Path(p) for p in job["source_paths"]]
            original_stats = [(p.stat().st_size, p.stat().st_mtime_ns) for p in sources]
            if any(size <= 0 for size, _ in original_stats):
                raise RuntimeError("녹화 파일이 비어 있습니다.")
            inputs = await asyncio.gather(
                *(asyncio.to_thread(probe_media, str(p)) for p in sources)
            )
            expected = {
                kind
                for media in inputs
                for kind in media["streams"]
                if kind in ("video", "audio")
            }
            if "video" not in expected:
                raise RuntimeError("원본에서 영상 스트림을 찾지 못했습니다.")
            duration = inputs[0]["duration"]
            job.update(
                state="converting",
                progress=None,
                processing_started_at=now(),
                error_message=None,
            )
            self._save(job)
            if job.get("inspect_only"):
                candidate = Path(
                    job.get("output_path") or job.get("temporary_output") or ""
                )
                if not candidate.is_file():
                    raise RuntimeError(
                        "검사할 변환 파일을 찾을 수 없습니다. 다시 변환하세요."
                    )
            elif job["target_format"] == "ts" and len(sources) == 1:
                candidate = sources[0]
            else:
                target_format = job["target_format"]
                stem = (
                    sources[0]
                    .stem.encode("utf-8")[:200]
                    .decode("utf-8", errors="ignore")
                )
                candidate = sources[0].with_name(
                    stem + f".{uuid.uuid4().hex}.converting.{target_format}"
                )
                job["temporary_output"] = str(candidate)
                self._save(job)
                cmd = [
                    get_settings().resolve_ffmpeg_path(),
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-nostdin",
                    "-n",
                ]
                for source in sources:
                    cmd += ["-i", str(source)]
                cmd += ["-map", "0:v?"]
                if len(sources) == 1:
                    cmd += ["-map", "0:a?"]
                else:
                    for index in range(1, len(sources)):
                        cmd += ["-map", f"{index}:a?"]
                cmd += ["-c", "copy"]
                if target_format == "mp4":
                    cmd += ["-movflags", "+faststart"]
                cmd += [
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    "-f",
                    {"mp4": "mp4", "mkv": "matroska", "ts": "mpegts"}[target_format],
                    str(candidate),
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )

                async def drain_stderr():
                    tail = bytearray()
                    while data := await proc.stderr.read(4096):
                        tail.extend(data)
                        if len(tail) > 65536:
                            del tail[:-65536]
                    return bytes(tail)

                async def progress():
                    while line := await proc.stdout.readline():
                        text = line.decode(errors="replace").strip()
                        if (
                            text.startswith("out_time_us=")
                            and duration
                            and duration > 0
                        ):
                            try:
                                job["progress"] = round(
                                    max(
                                        0,
                                        min(
                                            99,
                                            float(text.split("=", 1)[1])
                                            / 1000000
                                            / duration
                                            * 100,
                                        ),
                                    ),
                                    1,
                                )
                                self._save(job)
                            except ValueError:
                                pass

                stderr_task = asyncio.create_task(drain_stderr())
                await asyncio.wait_for(
                    asyncio.gather(progress(), proc.wait()), timeout=21600
                )
                stderr = redact_media_error(
                    (await stderr_task).decode(errors="replace"), max_length=65536
                )
                job["diagnostics"] = {"returncode": proc.returncode, "stderr": stderr}
                if proc.returncode != 0:
                    logger.warning(f"[{job_id}] 변환 실패: {stderr}")
                    raise RuntimeError(
                        "파일을 변환하지 못했습니다. 원본 TS를 보관했습니다. 오류 상세를 확인하거나 MKV로 다시 변환하세요."
                    )
            job.update(state="verifying", inspection_state="running")
            self._save(job)
            media = await asyncio.to_thread(probe_media, str(candidate))
            if (
                not expected.issubset(media["streams"])
                or not media["duration"]
                or media["size"] <= 0
            ):
                raise RuntimeError(
                    "변환 파일의 영상·음성 또는 재생 정보를 확인하지 못했습니다."
                )
            expected_container = {"mp4": "mp4", "mkv": "matroska", "ts": "mpegts"}[
                job["target_format"]
            ]
            if expected_container not in media["format_name"]:
                raise RuntimeError("변환 파일 형식이 선택한 형식과 다릅니다.")
            if duration and abs(media["duration"] - duration) > max(2, duration * 0.02):
                raise RuntimeError(
                    "원본과 변환 파일의 길이가 다릅니다. 원본을 보관했습니다."
                )
            if media["diagnostics"]["stderr"].strip():
                raise RuntimeError(
                    "파일 검사에서 오류가 보고되었습니다. 원본을 보관했습니다."
                )
            for kind in expected:
                before = [
                    t
                    for m in inputs
                    for t in m["tracks"]
                    if t.get("codec_type") == kind
                ]
                after = [t for t in media["tracks"] if t.get("codec_type") == kind]
                if len(before) != len(after):
                    raise RuntimeError("변환 후 스트림 개수가 달라졌습니다.")
                for source, output in zip(before, after):
                    if source.get("codec_name") != output.get("codec_name"):
                        raise RuntimeError("변환 후 코덱이 달라졌습니다.")
                    if kind == "video":
                        if (source.get("width"), source.get("height")) != (
                            output.get("width"),
                            output.get("height"),
                        ):
                            raise RuntimeError("변환 후 해상도가 달라졌습니다.")

                        def fps(track):
                            numerator, denominator = map(
                                float,
                                str(track.get("avg_frame_rate") or "0/1").split("/"),
                            )
                            return numerator / denominator if denominator else 0

                        if abs(fps(source) - fps(output)) > 0.1:
                            raise RuntimeError("변환 후 프레임레이트가 달라졌습니다.")
            if [
                (p.stat().st_size, p.stat().st_mtime_ns) for p in sources
            ] != original_stats:
                raise RuntimeError("변환 중 원본 파일이 변경되었습니다.")
            if candidate not in sources and not job.get("output_path"):
                target = sources[0].with_suffix("." + job["target_format"])
                number = 1
                while target.exists():
                    target = sources[0].with_name(
                        sources[0].stem + f" ({number})." + job["target_format"]
                    )
                    number += 1
                await asyncio.to_thread(publish_file, candidate, target)
            else:
                target = candidate
            job.update(
                state="completed",
                output_path=str(target),
                progress=100,
                inspection_state="passed",
                processing_completed_at=now(),
                file_size_bytes=target.stat().st_size,
                duration_seconds=media["duration"],
                inspection={
                    "format_name": media["format_name"],
                    "duration": media["duration"],
                    "tracks": media["tracks"],
                },
            )
            self._save(job)
            self.db.execute(
                "UPDATE live_history SET output_path=?,file_size_bytes=?,duration_seconds=? WHERE recording_job_id=?",
                (str(target), job["file_size_bytes"], media["duration"], job_id),
            )
            if not job["keep_source_ts"] and target not in sources:
                for source in sources:
                    try:
                        await asyncio.to_thread(source.unlink)
                    except OSError:
                        job["source_cleanup_warning"] = (
                            "변환은 완료되었지만 일부 원본 TS를 정리하지 못했습니다."
                        )
                        self._save(job)
            if self.on_finished:
                self.on_finished(job)
        except asyncio.CancelledError:
            job.update(
                state="attention",
                inspection_state="pending",
                progress=None,
                error_message="변환이 중단되었습니다. 원본 TS를 보관했습니다.",
            )
            self._save(job)
            raise
        except Exception as error:
            job.update(
                state="failed",
                progress=None,
                error_message=(
                    str(error)
                    if isinstance(error, RuntimeError)
                    else "변환 또는 파일 검사에 실패했습니다. 원본 TS를 보관했습니다."
                ),
                inspection_state="failed",
                processing_completed_at=now(),
            )
            job["diagnostics"]["detail"] = redact_media_error(error)
            logger.warning(f'[{job_id}] 후처리 실패: {job["diagnostics"]["detail"]}')
            self._save(job)
            if self.on_finished:
                self.on_finished(job)
        finally:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            if stderr_task:
                await asyncio.gather(stderr_task, return_exceptions=True)
