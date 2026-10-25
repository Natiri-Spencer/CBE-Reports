"""Single Alembic environment shared by backend and workspace entry points."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.database import Base, SQLALCHEMY_DATABASE_URL
from app.models import user, fee, marks, admin_activity, learner, request_receipt, security  # register all tables

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
    # Migration logging must preserve monitoring and keep request URLs private.
    import logging
    logging.getLogger("uvicorn.access").disabled = True
target_metadata = Base.metadata


def configure(connection=None):
    options = {"target_metadata": target_metadata, "compare_type": True}
    if connection is None:
        options.update(url=SQLALCHEMY_DATABASE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"})
    else:
        options.update(connection=connection, render_as_batch=connection.dialect.name == "sqlite")
        if connection.dialect.name == "sqlite":
            # Python sqlite3's legacy transaction mode does not begin a real
            # transaction for DDL. Begin explicitly so a failed migration rolls
            # back schema changes together with its data changes.
            if not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            options["transactional_ddl"] = True
    context.configure(**options)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    configure()
elif config.attributes.get("connection") is not None:
    configure(config.attributes["connection"])
else:
    with create_engine(SQLALCHEMY_DATABASE_URL, poolclass=pool.NullPool, hide_parameters=True).begin() as connection:
        configure(connection)
