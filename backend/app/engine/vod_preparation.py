"""Persistent CHZZK VOD preparation on the existing engine and repository."""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

from app.core.config import get_settings


def canonical_vod_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        match = re.fullmatch(r'/(video/[0-9]+|clips/[A-Za-z0-9_-]+)/?', parts.path)
        if (parts.scheme not in ('http', 'https') or parts.hostname != 'chzzk.naver.com'
                or parts.username or parts.password or parts.port not in (None, 80, 443) or not match):
            raise ValueError
        return f'https://chzzk.naver.com/{match[1]}'
    except ValueError:
        raise ValueError('CHZZK 다시보기 또는 클립 URL을 입력해 주세요.') from None


def quality_options(info: dict) -> list[dict]:
    heights = {f.get('height') for f in info.get('formats', [])
               if isinstance(f.get('height'), int) and f['height'] > 0
               and f.get('vcodec') != 'none'}
    return [{'value': f'{height}p', 'label': f'{height}p'} for height in sorted(heights, reverse=True)]


class VodPreparation:
    def prepare_vods(self, urls: list[str]) -> dict:
        from app.engine.vod import VodDownloadTask
        if self._shutting_down:
            raise ValueError('서버가 종료 중입니다.')
        if len(urls) > 100:
            raise ValueError('한 번에 최대 100개의 URL을 등록할 수 있습니다.')
        results = []
        for value in urls:
            try:
                url = canonical_vod_url(value)
            except ValueError as exc:
                results.append({'url': value, 'error': str(exc)})
                continue
            existing = next((task for task in self._tasks.values()
                             if task.url == url or self._same_vod(task.url, url)), None)
            if existing:
                results.append({'url': url, 'task_id': existing.task_id, 'duplicate': True})
                continue
            if sum(task.prepared for task in self._tasks.values()) >= 1000:
                results.append({'url': url, 'error': '다운로드 대기 목록은 최대 1,000건까지 추가할 수 있습니다.'})
                continue
            settings = get_settings()
            task = VodDownloadTask(url=url, title=url.rsplit('/', 1)[-1], prepared=True,
                                   phase='metadata', quality=settings.vod_default_quality, cdn=settings.chzzk_vod_cdn,
                                   output_dir=settings.effective_vod_download_dir(True), max_retries=5)
            self._tasks[task.task_id] = task
            self._schedule_metadata(task)
            results.append({'url': url, 'task_id': task.task_id, 'duplicate': False})
        self._save_history()
        return {'results': results}

    @staticmethod
    def _same_vod(left: str, right: str) -> bool:
        try:
            return canonical_vod_url(left) == right
        except ValueError:
            return False

    def _schedule_metadata(self, task) -> None:
        future = asyncio.create_task(self._prepare_metadata(task))
        self._metadata_tasks.add(future)
        future.add_done_callback(self._metadata_tasks.discard)

    async def _prepare_metadata(self, task) -> None:
        try:
            async with self._metadata_semaphore:
                if self._tasks.get(task.task_id) is not task:
                    return
                info = await self.get_video_info(task.url)
            if self._tasks.get(task.task_id) is not task:
                return
            options = quality_options(info)
            if not options:
                raise ValueError('사용 가능한 영상 화질을 가져오지 못했습니다.')
            task.title = info.get('title') or task.title
            task.metadata = {key: info.get(key) for key in
                             ('id', 'duration', 'thumbnail', 'uploader', 'profile_image', 'upload_date')}
            task.metadata['qualities'] = options
            available = [option['value'] for option in options]
            preference = task.quality
            if preference == 'worst':
                task.quality = available[-1]
            elif preference in available:
                task.quality = preference
            else:
                target = int(preference[:-1]) if re.fullmatch(r'[0-9]+p', preference) else None
                task.quality = next((v for v in available if target and int(v[:-1]) <= target), available[-1] if target else available[0])
                if target:
                    task.metadata['quality_fallback'] = True
            task.error_message = None
            task.phase = 'ready'
        except Exception as exc:
            if self._tasks.get(task.task_id) is not task:
                return
            task.phase = 'metadata_error'
            task.error_message = self._format_download_error(exc)
        finally:
            if self._tasks.get(task.task_id) is task:
                self._save_history()

    def retry_metadata(self, task_id: str) -> dict:
        task = self._prepared_task(task_id)
        if task.phase == 'metadata':
            return self.get_task_status(task_id)
        if task.phase not in ('metadata_error', 'ready'):
            raise ValueError('정보를 다시 조회할 수 없는 작업입니다.')
        task.phase = 'metadata'
        task.error_message = None
        self._schedule_metadata(task)
        self._save_history()
        return self.get_task_status(task_id)

    def _prepared_task(self, task_id: str, allow_queued: bool = False):
        from app.engine.vod import VodDownloadState
        task = self._tasks.get(task_id)
        if not task or not task.prepared or task.state != VodDownloadState.IDLE:
            raise ValueError('대기 중인 VOD 준비 작업이 아닙니다.')
        if task.download_task is not None and not task.download_task.done() and not (allow_queued and task.phase == "queued" and task.started_at is None):
            raise ValueError('이미 다운로드가 예약된 작업입니다.')
        return task

    def set_prepared_quality(self, task_id: str, quality: str) -> dict:
        task = self._prepared_task(task_id, allow_queued=True)
        if task.phase not in ("ready", "queued") or quality not in {item['value'] for item in task.metadata.get('qualities', [])}:
            raise ValueError('이 영상에서 제공하지 않는 화질입니다.')
        task.quality = quality
        task.metadata.pop('quality_fallback', None)
        self._save_history()
        return self.get_task_status(task_id)

    def start_prepared(self, task_id: str, cdn: str | None = None) -> dict:
        task = self._prepared_task(task_id)
        if self._shutting_down or task.phase != 'ready':
            raise ValueError('다운로드 준비가 완료되지 않았습니다.')
        selected = cdn or get_settings().chzzk_vod_cdn
        if selected not in ('default', 'akamai'):
            raise ValueError('지원하지 않는 CDN입니다.')
        # No await between check and reservation: concurrent starts cannot duplicate.
        task.cdn = selected
        task.phase = 'queued'
        task.cancel_flag = False
        task.download_task = asyncio.create_task(self._run_download(task_id))
        self._save_history()
        return self.get_task_status(task_id)

    def start_prepared_batch(self, task_ids: list[str] | None = None) -> dict:
        ids = list(dict.fromkeys(task_ids)) if task_ids is not None else [
            task.task_id for task in self._tasks.values()
            if task.prepared and task.phase == 'ready']
        results = []
        for task_id in ids:
            try:
                self.start_prepared(task_id)
                results.append({'task_id': task_id, 'started': True})
            except ValueError as exc:
                results.append({'task_id': task_id, 'error': str(exc)})
        return {'results': results}

    def remove_vod_task(self, task_id: str) -> dict:
        from app.engine.vod import VodDownloadState
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError('작업을 찾을 수 없습니다.')
        if task.state not in (VodDownloadState.IDLE, VodDownloadState.COMPLETED, VodDownloadState.ERROR):
            raise ValueError('진행 중인 작업은 먼저 취소해 주세요.')
        if task.inspection_state == 'running':
            raise ValueError('파일 검사 종료를 기다려 주세요.')
        if task.download_task is not None and not task.download_task.done():
            if task.started_at is not None:
                raise ValueError('작업 종료를 기다려 주세요.')
            task.cancel_flag = True
            task.download_task.cancel()
        del self._tasks[task_id]
        self._save_history()
        return {'deleted_count': 1, 'task_id': task_id}
