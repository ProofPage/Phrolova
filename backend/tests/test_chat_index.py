"""
test_chat_index.py
채팅 로그 인덱스와 조회 API 테스트.

가장 중요한 계약: 인덱스로 빨라지더라도 결과는 전수 조사와 완전히 같아야 한다.
녹화 중에는 파일이 계속 append되므로 증분 갱신도 정확해야 한다.
"""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.chat import (
    CHECKPOINT_INTERVAL,
    _encode_file_id,
    _load_index,
    _read_messages,
    router,
)
from app.core.config import get_settings

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def write_log(path: Path, rows: list[dict], *, trailing_newline: bool = True) -> None:
    """JSONL 로그를 만든다. 개행을 빼면 아카이버가 쓰는 도중인 상태가 된다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if not trailing_newline and body:
        body = body[:-1]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(body)


def append_log(path: Path, rows: list[dict]) -> None:
    with open(path, "a", encoding="utf-8", newline="") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def row(i: int, nickname: str = "시청자", message: str = "안녕") -> dict:
    return {
        "timestamp": f"2026-05-15T14:{i // 60 % 60:02d}:{i % 60:02d}",
        "user_id": f"u{i}",
        "nickname": nickname,
        "message": message,
    }


def brute_force(path: Path, page: int, limit: int, search=None, nickname=None):
    """최적화 이전 방식 — 전부 읽고 전부 파싱한 뒤 자른다. 정답지로 쓴다."""
    messages = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            messages.append({
                "timestamp": raw.get("timestamp", ""),
                "user_id": raw.get("user_id"),
                "nickname": raw.get("nickname", "Unknown"),
                "message": raw.get("message", ""),
            })
    if nickname:
        nick_lower = nickname.lower()
        messages = [m for m in messages if nick_lower in m["nickname"].lower()]
    if search:
        search_lower = search.lower()
        messages = [m for m in messages if search_lower in m["message"].lower()]
    start = (page - 1) * limit
    return messages[start:start + limit], len(messages)


# ── 인덱스 ───────────────────────────────────────────────

class TestIndex:
    def test_counts_messages(self, tmp_path):
        log = tmp_path / "a.jsonl"
        write_log(log, [row(i) for i in range(250)])

        assert _load_index(log).message_count == 250

    def test_blank_and_broken_lines_are_skipped(self, tmp_path):
        log = tmp_path / "b.jsonl"
        write_log(log, [row(0), row(1)])
        with open(log, "a", encoding="utf-8", newline="") as f:
            f.write("\n")
            f.write("{깨진 json}\n")
            f.write(json.dumps(row(2), ensure_ascii=False) + "\n")

        messages, total = _read_messages(log, page=1, limit=100)
        assert [m["user_id"] for m in messages] == ["u0", "u1", "u2"]
        assert total == 3

    def test_records_a_checkpoint_per_interval(self, tmp_path):
        log = tmp_path / "c.jsonl"
        count = CHECKPOINT_INTERVAL * 2 + 5
        write_log(log, [row(i) for i in range(count)])

        index = _load_index(log)
        assert index.message_count == count
        assert len(index.offsets) == 3  # 0번, INTERVAL번, 2*INTERVAL번 메시지

    def test_append_is_counted_incrementally(self, tmp_path):
        """녹화 중 파일이 자라도 처음부터 다시 읽지 않는다."""
        log = tmp_path / "d.jsonl"
        write_log(log, [row(i) for i in range(100)])
        first = _load_index(log)
        assert first.message_count == 100

        append_log(log, [row(i) for i in range(100, 130)])
        second = _load_index(log)

        assert second.message_count == 130
        assert second.offsets[0] == first.offsets[0]

    def test_partial_last_line_is_not_counted_until_complete(self, tmp_path):
        """아카이버가 쓰는 도중인 줄은 세지 않고, 완성되면 그때 센다."""
        log = tmp_path / "e.jsonl"
        write_log(log, [row(i) for i in range(10)], trailing_newline=False)

        assert _load_index(log).message_count == 9

        with open(log, "a", encoding="utf-8", newline="") as f:
            f.write("\n")

        assert _load_index(log).message_count == 10

    def test_shrunk_file_is_rebuilt(self, tmp_path):
        log = tmp_path / "f.jsonl"
        write_log(log, [row(i) for i in range(200)])
        assert _load_index(log).message_count == 200

        write_log(log, [row(i) for i in range(20)])
        assert _load_index(log).message_count == 20


# ── 조회 결과가 전수 조사와 같은가 ────────────────────────

class TestReadMatchesBruteForce:
    @pytest.fixture
    def log(self, tmp_path):
        path = tmp_path / "big.jsonl"
        rows = []
        for i in range(2500):
            rows.append(row(
                i,
                nickname=f"시청자{i % 37:02d}",
                message=("ㅋㅋㅋ 대박" if i % 3 == 0 else "그냥 인사"),
            ))
        # 원문 선필터가 놓치기 쉬운 이스케이프 케이스
        rows.append(row(9001, nickname="따옴표맨", message='그거 "진짜" 맞음'))
        rows.append(row(9002, nickname="역슬래시", message="C:\\경로\\파일"))
        rows.append(row(9003, nickname="대문자ABC", message="Hello WORLD"))
        write_log(path, rows)
        return path

    @pytest.mark.parametrize("page", [1, 2, 13, 25, 26, 500])
    def test_pagination(self, log, page):
        assert _read_messages(log, page, 100) == brute_force(log, page, 100)

    @pytest.mark.parametrize("term", ["ㅋㅋㅋ", "인사", "없는말zzz", "WORLD", "world"])
    def test_search(self, log, term):
        assert _read_messages(log, 1, 100, term, None) == brute_force(log, 1, 100, term, None)

    @pytest.mark.parametrize("term", ['"진짜"', "C:\\경로", "진짜", "경로"])
    def test_search_with_json_escaped_characters(self, log, term):
        """따옴표·역슬래시는 파일에 이스케이프돼 있어 원문 선필터가 놓친다."""
        assert _read_messages(log, 1, 100, term, None) == brute_force(log, 1, 100, term, None)

    @pytest.mark.parametrize("nick", ["시청자01", "시청자", "따옴표맨", "abc", "없음"])
    def test_nickname_filter(self, log, nick):
        assert _read_messages(log, 1, 100, None, nick) == brute_force(log, 1, 100, None, nick)

    def test_search_and_nickname_together(self, log):
        assert (_read_messages(log, 1, 100, "대박", "시청자03")
                == brute_force(log, 1, 100, "대박", "시청자03"))

    def test_page_beyond_end_is_empty(self, log):
        messages, total = _read_messages(log, 9999, 100)
        assert messages == []
        assert total == 2503


# ── API 엔드포인트 ───────────────────────────────────────

class TestChatApi:
    @pytest.fixture
    def archive(self, tmp_path):
        settings = get_settings()
        settings.download_dir = str(tmp_path)
        write_log(tmp_path / "채널A" / "s1.jsonl", [row(i) for i in range(150)])
        write_log(tmp_path / "채널B" / "s2.jsonl", [row(i) for i in range(7)])
        return tmp_path

    def test_file_list_reports_message_counts(self, archive):
        res = client.get("/api/chat/files")
        assert res.status_code == 200

        counts = {f["filename"]: f["message_count"] for f in res.json()}
        assert counts == {"s1.jsonl": 150, "s2.jsonl": 7}

    def test_file_list_is_stable_across_calls(self, archive):
        """두 번째 호출은 인덱스를 재사용한다 — 결과가 같아야 한다."""
        first = client.get("/api/chat/files").json()
        second = client.get("/api/chat/files").json()
        assert first == second

    def test_messages_are_paginated(self, archive):
        file_id = _encode_file_id(str(Path("채널A") / "s1.jsonl"))
        res = client.get(f"/api/chat/files/{file_id}/messages", params={"page": 2, "limit": 100})

        body = res.json()
        assert body["total"] == 150
        assert body["page"] == 2
        assert len(body["messages"]) == 50
        assert body["has_next"] is False

    def test_message_count_follows_appended_file(self, archive):
        """녹화가 진행되는 동안 목록의 개수가 따라 올라간다."""
        client.get("/api/chat/files")

        append_log(archive / "채널B" / "s2.jsonl", [row(i) for i in range(7, 20)])

        counts = {f["filename"]: f["message_count"] for f in client.get("/api/chat/files").json()}
        assert counts["s2.jsonl"] == 20

    def test_rejects_path_escape(self, archive):
        file_id = _encode_file_id("../../secret.jsonl")
        res = client.get(f"/api/chat/files/{file_id}/messages")
        assert res.status_code in (403, 404)
