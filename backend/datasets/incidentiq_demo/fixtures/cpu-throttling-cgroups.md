# Kubernetes Container CPU Throttling and CFS Quota

When service p99 latency spikes despite low average CPU utilization, inspect container_cpu_cfs_throttled_periods_total. High throttling indicates bursty thread concurrency exceeding CFS period quota. Increase CPU limits or remove CPU limits while keeping CPU requests for guaranteed scheduling.
