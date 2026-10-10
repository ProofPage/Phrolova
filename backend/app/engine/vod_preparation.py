"""Persistent CHZZK VOD preparation on the existing engine and repository."""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit, parse_qs

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
    from app.engine.platform_media import media_platform
    if media_platform(info.get('url', '')) == 'cime':
        formats = [f for f in info.get('formats', []) if f.get('height') and f.get('vcodec') != 'none']
        result, seen = [], set()
        for f in sorted(formats, key=lambda f: (f['height'], f.get('fps') or 0, f.get('tbr') or 0), reverse=True):
            key = (f['height'], f.get('fps') or 0)
            if key in seen: continue
            seen.add(key)
            fps = f.get('fps') or 0
            result.append({'value': f['format_id'], 'label': f"{f['height']}p" + (f' {fps:g}fps' if fps else ''),
                           'height': f['height'], 'width': f.get('width'), 'fps': fps or None, 'bitrate': (f.get('tbr') or 0)*1000 or None})
        return result
    heights = {f.get('height') for f in info.get('formats', [])
               if isinstance(f.get('height'), int) and f['height'] > 0
               and f.get('vcodec') != 'none'}
    return [{'value': f'{height}p', 'label': f'{height}p'} for height in sorted(heights, reverse=True)]


def canonical_prepared_url(value: str, source: str = 'chzzk') -> str:
    from app.engine.platform_media import media_platform, canonical_platform_video
    detected = media_platform(value)
    if detected in ('soop', 'cime'):
        return canonical_platform_video(value)
    if source in ('soop', 'cime'):
        raise ValueError('선택한 플랫폼의 다시보기 또는 클립 링크를 입력하세요.')
    if source == 'auto':
        source = detected
    if source == 'chzzk':
        return canonical_vod_url(value)
    from app.engine.vod import VodEngine, NonRetryableDownloadError
    value = value.strip()
    if source == 'youtube' and re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        value = f'https://www.youtube.com/watch?v={value}'
    try:
        VodEngine._validate_media_url(value)
    except NonRetryableDownloadError as exc:
        raise ValueError(str(exc)) from None
    parts = urlsplit(value)
    host = parts.hostname.lower()
    if source == 'youtube':
        if host == 'youtu.be':
            video_id = parts.path.strip('/')
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'):
            video_id = parse_qs(parts.query).get('v', [''])[0] if parts.path == '/watch' else parts.path.rstrip('/').split('/')[-1] if parts.path.startswith(('/shorts/', '/embed/', '/live/')) else ''
        else:
            raise ValueError('유튜브 영상 URL을 입력하세요.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise ValueError('채널 링크는 다운로드 시작으로 추가하세요.')
        return f'https://www.youtube.com/watch?v={video_id}'
    if source != 'external':
        raise ValueError('지원하지 않는 다운로드 소스입니다.')
    if host == 'chzzk.naver.com':
        return canonical_vod_url(value)
    return parts._replace(fragment='').geturl()


class VodPreparation:
    def prepare_vods(self, urls: list[str], source: str = 'chzzk') -> dict:
        from app.engine.vod import VodDownloadTask
        if self._shutting_down:
            raise ValueError('서버가 종료 중입니다.')
        if len(urls) > 100:
            raise ValueError('한 번에 최대 100개의 URL을 등록할 수 있습니다.')
        results = []
        for value in urls:
            try:
                url = canonical_prepared_url(value, source)
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
            is_chzzk = self._is_chzzk_url(url)
            task = VodDownloadTask(url=url, title=url.rsplit('/', 1)[-1], prepared=True,
                                   phase='metadata', quality=settings.vod_default_quality, cdn=settings.chzzk_vod_cdn,
                                   output_dir=settings.effective_vod_download_dir(is_chzzk), max_retries=5 if is_chzzk else 3)
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
            if not options and not self._is_chzzk_url(task.url) and any(fmt.get('vcodec') != 'none' for fmt in info.get('formats', [])):
                # Direct video URLs may have no advertised height; use a real yt-dlp selector.
                options = [{'value': 'best', 'label': '최고 화질'}]
            if not options:
                raise ValueError('사용 가능한 영상 화질을 가져오지 못했습니다.')
            task.title = info.get('title') or task.title
            task.metadata = {key: info.get(key) for key in
                             ('id', 'duration', 'thumbnail', 'uploader', 'profile_image', 'upload_date')}
            task.metadata['qualities'] = options
            available = [option['value'] for option in options]
            preference = task.quality
            if available == ['best']:
                task.quality = 'best'
                if preference not in ('best', 'worst'):
                    task.metadata['quality_fallback'] = True
            elif preference == 'worst':
                task.quality = available[-1]
            elif preference in available:
                task.quality = preference
            else:
                target = int(preference[:-1]) if re.fullmatch(r'[0-9]+p', preference) else None
                task.quality = next((o['value'] for o in options if target and (o.get('height') or (int(o['value'][:-1]) if re.fullmatch(r'\d+p', o['value']) else 0)) <= target), available[-1] if target else available[0])
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
