import pytest
from httpx import ASGITransport, AsyncClient

from rekamind_server.api import create_app
from rekamind_server.auth import routes as auth_routes
from rekamind_server.config import Settings
from rekamind_server.engines.fake import fake_engines


@pytest.fixture
async def client(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="none")
    app = create_app(settings, engines=fake_engines())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            c.app = app
            yield c


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    auth_routes._limiter._hits.clear()  # the limiter is process-wide; tests must not eat each other's budget
    yield
