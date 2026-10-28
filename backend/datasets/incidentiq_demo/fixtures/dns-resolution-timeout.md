# CoreDNS Query Amplification and UDP Timeout

When inter-service HTTP requests fail with dial tcp: lookup i/o timeout, inspect CoreDNS pod latency and UDP packet drops. High ndots settings in resolv.conf cause 5 redundant iterative lookups per query. Reduce ndots:2 and enable NodeLocal DNSCache daemonset.
