import pytest
from httpx import ASGITransport, AsyncClient

from rekamind_server.api import create_app
from rekamind_server.config import Settings
from rekamind_server.engines.fake import fake_engines


@pytest.fixture
async def client(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False)
    app = create_app(settings, engines=fake_engines())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app
            yield c
