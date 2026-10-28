# Distributed Lock Lease Expiration and Worker Starvation

When scheduled batch jobs execute concurrently and corrupt data, inspect Redlock lease duration and clock skew across Redis nodes. Check if worker execution exceeds lock TTL. Implement automatic lock renewal heartbeats or enforce pessimistic database row locking.
