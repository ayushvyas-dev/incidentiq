# PostgreSQL Deadlock and Row Lock Contention

When concurrent transactions report deadlock detected (error 40P01), inspect pg_stat_activity and pg_locks to identify conflicting transactions. Ensure application services acquire table locks in deterministic order. Check index coverage on foreign keys to prevent full-table share locks during updates.
