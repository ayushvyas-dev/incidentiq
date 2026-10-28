# Kafka Consumer Group Rebalance Storm and Lag

When consumer lag rises across partitions and rebalances recur continuously, inspect consumer heartbeat timeouts and max.poll.interval.ms. Check if message batch processing exceeds max.poll.interval.ms, causing group coordinator to evict consumers. Increase processing thread pool or decrease max.poll.records.
