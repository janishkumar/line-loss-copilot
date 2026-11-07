import os

import pytest


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("LINECOPILOT_TEST_DB_URL")
    if not url:
        pytest.skip("LINECOPILOT_TEST_DB_URL is not set")
    return url
