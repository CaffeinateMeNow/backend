"""Functions handling management of the postgres database schema."""

from mediawords.db import connect_to_db
from mediawords.db.handler import DatabaseHandler
from mediawords.util.log import create_logger
from mediawords.util.paths import mc_sql_schema_path

log = create_logger(__name__)


class McSchemaException(Exception):
    """Errors related to managing the database schema."""

    pass


# FIXME probably remove recreate_db()
def recreate_db() -> None:
    """(Re)create database schema.

    This function drops all objects in all schemas and reruns the schema/mediawords.sql to recreate the schema
    (and erase all data!) for the given database.

    This function will refuse to run if there are more than 10 million stories in the database, under the assumption
    that the database might be a production database in that case.
    """
    db = connect_to_db(do_not_check_schema_version=True)
    initialize_with_schema(db=db)


def initialize_with_schema(db: DatabaseHandler) -> None:
    """Initialize database with a fresh schema."""

    def reset_all_schemas(db_: DatabaseHandler) -> None:
        """Recreate all schemas."""
        schemas = db_.query("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT LIKE %(schema_pattern)s
              AND schema_name != 'information_schema'
            ORDER BY schema_name
        """, {'schema_pattern': 'pg_%'}).flat()

        # When dropping schemas, PostgreSQL spits out a lot of notices which break "no warnings" unit test
        db_.query('SET client_min_messages=WARNING')

        for schema in schemas:
            db_.query('DROP SCHEMA IF EXISTS %s CASCADE' % schema)

        db_.query('SET client_min_messages=NOTICE')

    # ---

    log.info("Resetting all schemas...")
    reset_all_schemas(db_=db)

    db.set_show_error_statement(True)

    mediawords_sql_path = mc_sql_schema_path()
    log.info("Importing from %s..." % mediawords_sql_path)
    with open(mediawords_sql_path, 'r') as mediawords_sql_f:
        mediawords_sql = mediawords_sql_f.read()
        db.query(mediawords_sql)

    log.info("Done.")
