# PostgreSQL Autovacuum Freeze and Transaction ID Wraparound

When PostgreSQL logs warnings regarding oldest un-vacuumed transaction ID or enters read-only mode, inspect pg_database datfrozenxid and vacuum_freeze_table_age. Cancel non-critical long-running queries and run manual VACUUM FREEZE ANALYZE on critical transaction tables.
