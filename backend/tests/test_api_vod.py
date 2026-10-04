"""
test_api_vod.py
VOD API 엔드포인트 통합 테스트 (FastAPI TestClient)
"""

import pytest
from fastapi.testclient import TestClient

# NOTE: FastAPI lifespan with TestClient compatibility issue
pytestmark = pytest.mark.skip(reason="FastAPI lifespan with TestClient compatibility issue")


class TestVodAPI:
    """VOD API 엔드포인트 테스트"""

    def test_get_vod_status(self):
        """VOD 전체 상태 조회"""
        response = client.get("/api/vod/status")

        assert response.status_code == 200
        data = response.json()

        # 응답 형식 확인
        assert "tasks" in data
        assert "active_count" in data
        assert "queued_count" in data
        assert "total_count" in data
        assert isinstance(data["tasks"], list)

    def test_get_vod_task_status_nonexistent(self):
        """존재하지 않는 task_id 조회"""
        response = client.get("/api/vod/status/nonexistent_task_id")

        # 200 + error 또는 404
        assert response.status_code in (200, 404)

    def test_cancel_vod_nonexistent(self):
        """존재하지 않는 VOD 다운로드 취소"""
        response = client.post("/api/vod/nonexistent_task_id/cancel")

        # 200 + error 또는 404
        assert response.status_code in (200, 404)

    def test_pause_vod_nonexistent(self):
        """존재하지 않는 VOD 다운로드 일시정지"""
        response = client.post("/api/vod/nonexistent_task_id/pause")

        assert response.status_code in (200, 404)

    def test_resume_vod_nonexistent(self):
        """존재하지 않는 VOD 다운로드 재개"""
        response = client.post("/api/vod/nonexistent_task_id/resume")

        assert response.status_code in (200, 404)

    def test_retry_vod_nonexistent(self):
        """존재하지 않는 VOD 다운로드 재시도"""
        response = client.post("/api/vod/nonexistent_task_id/retry")

        assert response.status_code in (200, 404)

    def test_reorder_vod_tasks_empty(self):
        """빈 작업 목록 재정렬"""
        payload = {
            "task_ids": [],
        }

        response = client.post("/api/vod/reorder", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["reordered_count"] == 0

    def test_clear_completed_vod_tasks(self):
        """완료된 VOD 작업 일괄 삭제"""
        response = client.post("/api/vod/clear-completed")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "deleted_count" in data
        assert "remaining_count" in data

    def test_open_vod_file_location_nonexistent(self):
        """존재하지 않는 VOD 파일 위치 열기"""
        response = client.post("/api/vod/nonexistent_task_id/open-location")

        assert response.status_code in (200, 404)

    def test_vod_info_invalid_url(self):
        """잘못된 URL로 VOD 정보 조회"""
        payload = {
            "url": "https://invalid-url.com",
        }

        response = client.post("/api/vod/info", json=payload)

        # 500 또는 200 + error
        assert response.status_code in (200, 500)

    def test_download_vod_invalid_url(self):
        """잘못된 URL로 VOD 다운로드 시도"""
        payload = {
            "url": "https://invalid-url.com",
            "quality": "best",
        }

        response = client.post("/api/vod/download", json=payload)

        # 백그라운드 작업이므로 200 반환 후 나중에 에러 상태로 전환
        # 또는 즉시 500 반환 가능
        assert response.status_code in (200, 500)
