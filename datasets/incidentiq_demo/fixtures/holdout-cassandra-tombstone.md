# Cassandra Read Timeout Due to Tombstone Overload

When Cassandra queries against telemetry tables fail with ReadFailureException or tombstone warning, inspect tombstone_warn_threshold and tombstone_failure_threshold. Heavy DELETE or TTL expirations create millions of tombstones. Run nodetool garbagecollect and tune gc_grace_seconds.
