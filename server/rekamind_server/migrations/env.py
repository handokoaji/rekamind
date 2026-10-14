"""Alembic environment. Migrations always run on a connection handed in by the
application (config.attributes["connection"]), so the same code path serves the
API process, a standalone worker, SQLite in-memory tests and Postgres."""

from alembic import context

from rekamind_server.models import Base

config = context.config
connection = config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Migrasi dijalankan lewat rekamind_server.db.migrate(), bukan CLI alembic langsung.")

context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,  # SQLite cannot ALTER most things in place
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
