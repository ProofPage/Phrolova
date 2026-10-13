from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
import pytest
from app.core.error_messages import localized_http_error, localized_validation_error
from fastapi.exceptions import RequestValidationError

@pytest.mark.parametrize('status,key', [(400,'errors.invalidInput'),(403,'errors.authentication'),(404,'errors.notFound'),(409,'errors.conflict'),(429,'errors.rateLimited'),(500,'errors.server'),(502,'errors.network'),(504,'errors.timeout')])
def test_localization_only_adds_key_without_altering_diagnostics(status,key):
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException,localized_http_error)
    @app.get('/fixture')
    def fail():
        raise HTTPException(status, {'error_code':'fixture','message':'기술 원문과 경로 C:/recordings/영상.ts'}, headers={'Retry-After':'7'})
    response = TestClient(app).get('/fixture')
    assert response.status_code == status
    assert response.headers['Retry-After'] == '7'
    assert response.json() == {'detail':{'error_code':'fixture','message':'기술 원문과 경로 C:/recordings/영상.ts'},'message_key':key}


def test_validation_keeps_fastapi_details_and_status():
    baseline, localized = FastAPI(), FastAPI()
    for app in (baseline, localized):
        @app.get('/fixture')
        def validate(count: int):
            return {'count': count}
    localized.add_exception_handler(RequestValidationError, localized_validation_error)
    original = TestClient(baseline).get('/fixture?count=invalid')
    translated = TestClient(localized).get('/fixture?count=invalid')
    assert translated.status_code == original.status_code == 422
    assert translated.json()['detail'] == original.json()['detail']
    assert translated.json()['message_key'] == 'errors.invalidInput'
