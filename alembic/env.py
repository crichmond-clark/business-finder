from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from business_finder import models  # noqa: F401
from business_finder.database import Base, get_database_engine_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url, connect_args = get_database_engine_config()
config.set_main_option("sqlalchemy.url", database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url, connect_args=connect_args, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
