# Kubernetes Pod OOMKilled and Memory Cgroup Limits

When containers terminate with exit code 137 (OOMKilled), inspect dmesg and Kubernetes event logs for memory cgroup limit exceeded. Compare container memory limit with application heap and off-heap allocations. For JVM/Node services, adjust maximum heap limit (-Xmx) to 75% of container memory limit.
