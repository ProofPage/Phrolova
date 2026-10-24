"""
Phrolova: 채널별 감시 시간대

모든 채널을 같은 주기로 확인하면 상시 방송 채널에는 맞지만,
정해진 시간에만 켜는 채널에는 쓸모없는 확인이 대부분이다.
이 모듈은 저장된 시간대(schedule)를 보고 "지금 확인할 때인가"를 판단한다.

저장 형식(JSON):
    {
        "mode": "always" | "scheduled",
        "windows": [{"days": [0, 2], "start": "22:00", "end": "23:30"}],
        "lead_minutes": 10,     # 시작 전 미리 확인
        "delay_minutes": 30     # 시작이 늦어질 때 계속 확인
    }
days는 월요일=0 기준이다.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from typing import Optional

#: 하루를 넘어가는 시간대를 찾을 때 훑어보는 일수.
_LOOKBACK_DAYS = 7


def parse_schedule(raw: Optional[str]) -> Optional[dict]:
    """저장된 JSON을 읽는다. 비었거나 깨졌으면 None(상시 감시)이다."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parse_clock(value) -> Optional[time]:
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except ValueError:
        return None


def _window_range(window: dict, day: datetime) -> Optional[tuple[datetime, datetime]]:
    """한 시간대를 실제 시작·끝 시각으로 바꾼다. 형식이 틀리면 None."""
    start_clock = _parse_clock(window.get("start"))
    end_clock = _parse_clock(window.get("end"))
    if start_clock is None or end_clock is None:
        return None
    begin = datetime.combine(day.date(), start_clock)
    finish = datetime.combine(day.date(), end_clock)
    if finish <= begin:
        finish += timedelta(days=1)
    return begin, finish


def _covers(window: dict, now: datetime, lead: timedelta = timedelta(), delay: timedelta = timedelta()) -> bool:
    try:
        days = {int(day) for day in window.get("days") or []}
    except (TypeError, ValueError):
        return False
    if not days:
        return False
    for offset in range(-1, _LOOKBACK_DAYS):
        day = now - timedelta(days=offset)
        if day.weekday() not in days:
            continue
        span = _window_range(window, day)
        if span and span[0] - lead <= now < span[1] + delay:
            return True
    return False


def is_within(schedule: Optional[dict], now: datetime) -> bool:
    """지금이 설정된 시간대 안인가. 상시 감시(mode!=scheduled)면 항상 True.

    시작 전 여유(lead)를 포함한다 — 그 전부터 확인을 시작해야 하기 때문이다.
    """
    if not schedule or schedule.get("mode") != "scheduled":
        return True
    lead = timedelta(minutes=_number(schedule.get("lead_minutes")))
    return any(_covers(window, now, lead) for window in schedule.get("windows") or [])


def is_active(schedule: Optional[dict], live_started_at: Optional[str], now: datetime) -> bool:
    """지금 확인해야 하는가.

    여유 시간 안이면 확인한다 — 대기 시간은 시작 전 / 지연 대기 / 끝난 뒤 확인 폭 중
    큰 값을 쓴다. 시간대보다 짧게만 기다리게 두면 예정보다 늦은 방송을 놓친다.
    방송이 이미 감지됐다면 끝까지 본다 — 끝 시간을 지나도 녹화 중인 방송을 자르지 않는다.
    """
    if schedule is None or schedule.get("mode") != "scheduled":
        return True
    if is_within(schedule, now):
        return True
    lead = timedelta(minutes=_number(schedule.get("lead_minutes")))
    delay = timedelta(minutes=_number(schedule.get("delay_minutes")))
    if any(_covers(window, now, lead, delay) for window in schedule.get("windows") or []):
        return True
    if not live_started_at:
        return False
    try:
        started = datetime.fromisoformat(live_started_at)
    except ValueError:
        return False
    if started.tzinfo is not None:
        started = started.astimezone(now.tzinfo).replace(tzinfo=now.tzinfo)
    wait = timedelta(
        minutes=max(
            _number(schedule.get("lead_minutes")),
            _number(schedule.get("delay_minutes")),
        )
    )
    if now - started <= wait:
        return True
    return _started_within_window(schedule, started)


def _number(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _started_within_window(schedule: dict, started: datetime) -> bool:
    """방송이 시간대 안(시작 전 여유 포함)에서 시작됐는가.

    그렇다면 끝 시간을 조금 넘더라도 계속 확인해서 녹화를 이어간다.
    """
    lead = timedelta(minutes=_number(schedule.get("lead_minutes")))
    for window in schedule.get("windows") or []:
        try:
            days = {int(day) for day in window.get("days") or []}
        except (TypeError, ValueError):
            continue
        for offset in range(_LOOKBACK_DAYS):
            day = started - timedelta(days=offset)
            if day.weekday() not in days:
                continue
            span = _window_range(window, day)
            if span and span[0] - lead <= started < span[1]:
                return True
    return False


def next_check_at(schedule: Optional[dict], now: datetime) -> Optional[datetime]:
    """다음 시간대가 시작되는 시각. 상시 감시면 None.

    감시 루프는 이 시각까지 대기했다가 깨어나 확인을 재개한다.
    """
    if not schedule or schedule.get("mode") != "scheduled":
        return None
    lead = timedelta(minutes=_number(schedule.get("lead_minutes")))
    candidates: list[datetime] = []
    for offset in range(_LOOKBACK_DAYS + 1):
        day = now + timedelta(days=offset)
        for window in schedule.get("windows") or []:
            try:
                days = {int(item) for item in window.get("days") or []}
            except (TypeError, ValueError):
                continue
            if day.weekday() not in days:
                continue
            span = _window_range(window, day)
            if span is None:
                continue
            opens = span[0] - lead
            if opens > now:
                candidates.append(opens)
    return min(candidates) if candidates else None


def describe(schedule: Optional[dict]) -> str:
    """로그·상태 표시용 짧은 설명."""
    if not schedule or schedule.get("mode") != "scheduled":
        return "상시 감시"
    windows = schedule.get("windows") or []
    if not windows:
        return "예약 감시 (시간대 없음)"
    return f"예약 감시 ({len(windows)}개 시간대)"
