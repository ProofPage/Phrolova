"""
test_logs_api.py
시스템 로그 조회 API (/api/system/logs) 작동 및 보안 검증 테스트
"""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from unittest.mock import patch

from app.api.system import router

# 테스트용 FastAPI 인스턴스 생성 및 라우터 마운트 (lifespan 종속성 격리)
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def temp_log_dir(tmp_path):
    """테스트용 임시 로그 디렉토리를 생성하고 복수의 로그 파일을 배치한다."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    
    # 1. 메인 로그 파일 (newline="\n" 설정하여 Windows 환경에서도 LF로 바이트 크기 일치시킴)
    main_log = log_dir / "service.log"
    with open(main_log, "w", encoding="utf-8", newline="\n") as f:
        f.write("line 1\nline 2\nline 3\nline 4\nline 5\n")
    
    # 2. 백업 로그 파일 1
    backup_log1 = log_dir / "service.log.2026-06-19"
    with open(backup_log1, "w", encoding="utf-8", newline="\n") as f:
        f.write("old line A\nold line B\n")
    
    # 3. 백업 로그 파일 2
    backup_log2 = log_dir / "service.log.2026-06-18"
    with open(backup_log2, "w", encoding="utf-8", newline="\n") as f:
        f.write("very old line\n")
    
    # 4. 관련 없는 다른 파일 (조회 대상에서 제외되어야 함)
    other_file = log_dir / "not_a_log.txt"
    other_file.write_text("should be ignored", encoding="utf-8")
    
    return log_dir


def test_list_system_logs(temp_log_dir):
    """로그 파일 목록 조회 API가 올바른 메타데이터를 반환하는지 테스트"""
    # app.api.system._get_log_dir 가 temp_log_dir를 가리키도록 패치
    with patch("app.api.system._get_log_dir", return_value=temp_log_dir):
        response = client.get("/api/system/logs")
        assert response.status_code == 200
        data = response.json()
        
        # service.log* 파일들이 조회되어야 함
        filenames = [item["filename"] for item in data]
        assert "service.log" in filenames
        assert "service.log.2026-06-19" in filenames
        assert "service.log.2026-06-18" in filenames
        assert "not_a_log.txt" not in filenames
        
        # 파일 크기 검증 (LF 개행 기준으로 정확히 35바이트)
        service_log_item = next(item for item in data if item["filename"] == "service.log")
        assert service_log_item["size_bytes"] == len("line 1\nline 2\nline 3\nline 4\nline 5\n")
        assert "modified_at" in service_log_item


def test_get_system_log_content_all(temp_log_dir):
    """특정 로그 파일 전체 읽기 테스트"""
    with patch("app.api.system._get_log_dir", return_value=temp_log_dir):
        response = client.get("/api/system/logs/service.log", params={"lines": 0})
        assert response.status_code == 200
        data = response.json()
        
        assert data["filename"] == "service.log"
        assert data["content"] == "line 1\nline 2\nline 3\nline 4\nline 5\n"
        assert data["total_lines"] == 5
        assert data["lines_returned"] == 5


def test_get_system_log_content_tail(temp_log_dir):
    """특정 로그 파일 최근 N줄 읽기 테스트"""
    with patch("app.api.system._get_log_dir", return_value=temp_log_dir):
        # 최근 2줄만 가져오기
        response = client.get("/api/system/logs/service.log", params={"lines": 2})
        assert response.status_code == 200
        data = response.json()
        
        assert data["filename"] == "service.log"
        assert data["content"] == "line 4\nline 5\n"
        assert data["total_lines"] == 5
        assert data["lines_returned"] == 2


def test_get_system_log_path_traversal_protection(temp_log_dir):
    """상위 경로 탐색을 통한 파일 강제 접근(Path Traversal) 공격 방어 테스트"""
    with patch("app.api.system._get_log_dir", return_value=temp_log_dir):
        # logs 디렉토리를 벗어나는 파일명 요청
        bad_filenames = [
            "..%2Fapp%2Fmain.py",
            "..%5Capp%5Cmain.py",
            "%2Fetc%2Fpasswd",
            "C:%5CWindows%5Cwin.ini",
        ]
        
        for name in bad_filenames:
            response = client.get(f"/api/system/logs/{name}")
            # Path Traversal 시도는 400 Bad Request 로 차단되어야 함
            assert response.status_code == 400
            assert "Invalid log file" in response.json()["detail"]
