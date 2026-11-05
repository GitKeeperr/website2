from fastapi.testclient import TestClient
from app import app


def test_healthcheck_requires_no_login():
    response = TestClient(app).get('/healthz')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
