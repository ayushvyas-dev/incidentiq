from fastapi.testclient import TestClient

from incidentiq.main import create_app

TEST_API_TOKEN = "incidentiq-test-token-" + "x" * 40
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_TOKEN}"}


def create_test_app(*args, **kwargs):
    return create_app(*args, api_token=TEST_API_TOKEN, **kwargs)


def authorized_client(app) -> TestClient:
    return TestClient(app, headers=AUTH_HEADERS, backend_options={"use_uvloop": True})
