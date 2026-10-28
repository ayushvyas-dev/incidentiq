# Redis Memory Eviction and Maxmemory Saturation

When Redis returns OOM command not allowed or cache hit rate drops sharply, check used_memory versus maxmemory. Inspect evicted_keys and instantaneous_ops_per_sec. Verify eviction policy (volatile-lru vs allkeys-lru). Identify hot keys using redis-cli --hotkeys and configure TTL on ephemeral session keys.
