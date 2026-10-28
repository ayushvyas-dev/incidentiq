"""Generate rich operational runbooks and 200 versioned evaluation cases.

Includes:
- 150 validation cases (112 answerable, 38 unanswerable)
- 50 holdout cases (36 answerable, 14 unanswerable)
Total: 200 cases, 52 unanswerable cases.
Zero leakage between validation and holdout splits.
"""

import json
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parents[2]
DATASETS_DIR = BASE_DIR / "datasets" / "incidentiq_demo"
BACKEND_DATASETS_DIR = BASE_DIR / "backend" / "datasets" / "incidentiq_demo"

FIXTURES = {
    # Existing fixture preserved and enhanced
    "connection-pool.md": """# Database connection pool

When acquisition timeouts rise, inspect connection pool saturation and connection leaks. Compare active connections with the configured pool size before changing pool settings. Check for unclosed transactions and long-running queries holding idle-in-transaction locks.
""",

    "db-deadlock-resolution.md": """# PostgreSQL Deadlock and Row Lock Contention

When concurrent transactions report deadlock detected (error 40P01), inspect pg_stat_activity and pg_locks to identify conflicting transactions. Ensure application services acquire table locks in deterministic order. Check index coverage on foreign keys to prevent full-table share locks during updates.
""",

    "redis-memory-eviction.md": """# Redis Memory Eviction and Maxmemory Saturation

When Redis returns OOM command not allowed or cache hit rate drops sharply, check used_memory versus maxmemory. Inspect evicted_keys and instantaneous_ops_per_sec. Verify eviction policy (volatile-lru vs allkeys-lru). Identify hot keys using redis-cli --hotkeys and configure TTL on ephemeral session keys.
""",

    "kafka-consumer-lag.md": """# Kafka Consumer Group Rebalance Storm and Lag

When consumer lag rises across partitions and rebalances recur continuously, inspect consumer heartbeat timeouts and max.poll.interval.ms. Check if message batch processing exceeds max.poll.interval.ms, causing group coordinator to evict consumers. Increase processing thread pool or decrease max.poll.records.
""",

    "rabbitmq-queue-spill.md": """# RabbitMQ Queue Memory Alarm and Unacked Messages

When RabbitMQ triggers memory alarm or publisher confirms block, inspect unacknowledged message counts and prefetch limits on consumers. Verify worker acknowledgment rate and ensure consumer channel prefetch is bounded between 50 and 200. Check dead letter exchange routing.
""",

    "k8s-pod-oom.md": """# Kubernetes Pod OOMKilled and Memory Cgroup Limits

When containers terminate with exit code 137 (OOMKilled), inspect dmesg and Kubernetes event logs for memory cgroup limit exceeded. Compare container memory limit with application heap and off-heap allocations. For JVM/Node services, adjust maximum heap limit (-Xmx) to 75% of container memory limit.
""",

    "cpu-throttling-cgroups.md": """# Kubernetes Container CPU Throttling and CFS Quota

When service p99 latency spikes despite low average CPU utilization, inspect container_cpu_cfs_throttled_periods_total. High throttling indicates bursty thread concurrency exceeding CFS period quota. Increase CPU limits or remove CPU limits while keeping CPU requests for guaranteed scheduling.
""",

    "ingress-504-gateway.md": """# Ingress 504 Gateway Timeout and Upstream Keepalive

When edge ingress proxies return 504 Gateway Timeout, inspect upstream keepalive timeout mismatch between proxy and backend server. If backend keepalive timeout is shorter than proxy keepalive timeout, proxy sends requests to closing connections. Set backend keepalive timeout at least 5 seconds higher than proxy.
""",

    "tls-cert-rotation.md": """# TLS Certificate Rotation and Handshake Errors

When clients report SSL handshake failure or SEC_ERROR_EXPIRED_CERTIFICATE, inspect cert-manager Certificate and CertificateRequest status. Verify Let's Encrypt ACME HTTP-01 challenge ingress routes. Check secret synchronization across Kubernetes namespaces.
""",

    "dns-resolution-timeout.md": """# CoreDNS Query Amplification and UDP Timeout

When inter-service HTTP requests fail with dial tcp: lookup i/o timeout, inspect CoreDNS pod latency and UDP packet drops. High ndots settings in resolv.conf cause 5 redundant iterative lookups per query. Reduce ndots:2 and enable NodeLocal DNSCache daemonset.
""",

    "jwt-jwks-fetch-failure.md": """# JWT Verification Failure and JWKS Key Rotation

When authentication service returns 401 Unauthorized for valid tokens after IdP key rotation, check JWKS cache TTL and outbound network connectivity to identity provider well-known endpoint. Ensure JWKS client supports stale-while-revalidate and caches public keys across transient network errors.
""",

    "payment-gateway-timeout.md": """# Payment Gateway Latency and Circuit Breaker Tripping

When checkout transactions fail with payment gateway timeout, inspect circuit breaker state metrics for payment-service. Verify whether error threshold tripped the breaker into OPEN state. Check secondary payment gateway fallback health and switch traffic routing to backup acquirer.
""",

    "s3-throughput-throttle.md": """# AWS S3 503 SlowDown and Partition Key Hotspotting

When object storage uploads or downloads receive HTTP 503 SlowDown responses, verify S3 request rate limits (3,500 PUT/5,500 GET per second per prefix). Implement hash-based prefix partitioning for object keys. Apply exponential backoff with full jitter in the storage client SDK.
""",

    "postgres-vacuum-freeze.md": """# PostgreSQL Autovacuum Freeze and Transaction ID Wraparound

When PostgreSQL logs warnings regarding oldest un-vacuumed transaction ID or enters read-only mode, inspect pg_database datfrozenxid and vacuum_freeze_table_age. Cancel non-critical long-running queries and run manual VACUUM FREEZE ANALYZE on critical transaction tables.
""",

    "grpc-deadline-exceeded.md": """# gRPC DEADLINE_EXCEEDED Cascade Across Microservices

When client calls fail with DEADLINE_EXCEEDED (status code 4), verify context deadline propagation across internal RPC hops. Missing context deadline subtraction causes upstream timeouts while downstream work continues needlessly. Ensure deadline propagation and set aggressive client timeouts.
""",

    "auth-rate-limiting.md": """# API Rate Limiter Saturation and 429 Cascades

When legitimate client requests receive 429 Too Many Requests, inspect Redis token bucket counters and IP reputation tiers. Check if corporate proxies or shared NAT gateways share IP rate limit buckets. Configure authenticated user rate limiting by customer ID rather than client IP.
""",

    "elasticsearch-circuit-breaker.md": """# Elasticsearch DataTooLargeException and Fielddata Breaker

When log search or document query fails with DataTooLargeException, inspect Elasticsearch JVM heap usage and parent circuit breaker statistics. Avoid running unconstrained wildcard aggregations on analyzed text fields. Increase indices.breaker.total.use_real_memory threshold.
""",

    "cdn-cache-poisoning.md": """# CDN 502 Error Caching and Emergency Cache Purge

When CDN edge nodes serve cached 502 Bad Gateway responses after upstream service recovery, inspect Cache-Control headers on origin error responses. Ensure origin sets Cache-Control: no-cache, no-store for 5xx errors. Trigger targeted CDN tag-based cache purge.
""",

    "websocket-connection-exhaustion.md": """# WebSocket File Descriptor Exhaustion and EMFILE

When realtime notification gateway refuses new WebSocket connections with error EMFILE: too many open files, inspect process file descriptor count vs ulimit -n. Adjust systemd LimitNOFILE to 65536 and tune sysctl fs.file-max to handle high concurrent persistent socket connections.
""",

    "distributed-lock-starvation.md": """# Distributed Lock Lease Expiration and Worker Starvation

When scheduled batch jobs execute concurrently and corrupt data, inspect Redlock lease duration and clock skew across Redis nodes. Check if worker execution exceeds lock TTL. Implement automatic lock renewal heartbeats or enforce pessimistic database row locking.
""",

    # Holdout fixtures (strictly separate corpus)
    "holdout-cassandra-tombstone.md": """# Cassandra Read Timeout Due to Tombstone Overload

When Cassandra queries against telemetry tables fail with ReadFailureException or tombstone warning, inspect tombstone_warn_threshold and tombstone_failure_threshold. Heavy DELETE or TTL expirations create millions of tombstones. Run nodetool garbagecollect and tune gc_grace_seconds.
""",

    "holdout-istio-sidecar-crash.md": """# Istio Envoy Sidecar Out of Memory CrashLoop

When application pods report upstream connect error or Envoy proxy crashes, inspect proxy_init and istio-proxy container exit codes. High inbound connection rates or large xDS route clusters cause Envoy memory exhaustion. Allocate higher memory limit to istio-proxy sidecar.
""",

    "holdout-stripe-webhook-lag.md": """# Stripe Webhook Processing Lag and Signature Verification

When billing webhook handler falls behind event arrival rate, inspect webhook signature verification latency and Redis job queue depth. Long database transactions in webhook thread pool block incoming deliveries. Separate webhook ingestion from processing with an async worker.
""",

    "holdout-dynamodb-throttling.md": """# DynamoDB ProvisionedThroughputExceededException

When user session lookup fails with ProvisionedThroughputExceededException, inspect partition key access distribution. Hot partitions overload single partition limits (1000 WCU / 3000 RCU). Add random suffix salting to partition keys or switch to DynamoDB On-Demand capacity mode.
""",

    "holdout-clickhouse-merge-tree.md": """# ClickHouse Too Many Parts in All Parts in Table

When analytical event ingestion fails with DB::Exception: Too many parts in all data parts in table, verify write batch sizes. Frequent single-row INSERTs create hundreds of tiny parts faster than background merges can consolidate. Buffer writes and insert batches of at least 10,000 rows.
""",
}


def build_validation_cases():
    cases = []
    
    # 1. Connection Pool (Checkout)
    for i in range(1, 10):
        cases.append({
            "case_id": f"val_conn_pool_{i:02d}",
            "incident": {
                "title": f"Checkout database acquisition timeouts during peak traffic {i}",
                "description": f"PostgreSQL connection acquisition timeouts rose to {100 + i*15}ms after release. Worker threads blocked waiting for database connections.",
                "service": "checkout",
                "environment": "production",
                "severity": "SEV-2" if i % 2 == 0 else "SEV-1",
            },
            "expected_relevant_sources": ["connection-pool.md"],
            "expected_facts": ["inspect connection pool saturation", "configured pool size"],
            "should_abstain": False,
        })

    # 2. Deadlock & Row Lock Contention
    for i in range(1, 9):
        cases.append({
            "case_id": f"val_deadlock_{i:02d}",
            "incident": {
                "title": f"PostgreSQL transaction deadlock 40P01 on orders update {i}",
                "description": f"Concurrent updates to orders table failed with deadlock detected. pg_stat_activity reports conflicting row exclusive locks.",
                "service": "checkout",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["db-deadlock-resolution.md"],
            "expected_facts": ["inspect pg_stat_activity and pg_locks", "deterministic order"],
            "should_abstain": False,
        })

    # 3. Redis Memory Eviction
    for i in range(1, 9):
        cases.append({
            "case_id": f"val_redis_evict_{i:02d}",
            "incident": {
                "title": f"Redis cache memory saturation and hit rate drop {i}",
                "description": f"Redis OOM errors reported by catalog cache. Hit rate dropped from 94% to 41% with high evicted_keys count.",
                "service": "catalog",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["redis-memory-eviction.md"],
            "expected_facts": ["used_memory versus maxmemory", "configure ttl"],
            "should_abstain": False,
        })

    # 4. Kafka Consumer Lag
    for i in range(1, 9):
        cases.append({
            "case_id": f"val_kafka_lag_{i:02d}",
            "incident": {
                "title": f"Kafka consumer group rebalance storm and lag spike {i}",
                "description": f"Order processing consumer group undergoing continuous rebalances. Partition lag exceeded {50000 + i*5000} messages.",
                "service": "order-processing",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["kafka-consumer-lag.md"],
            "expected_facts": ["max.poll.interval.ms", "consumer heartbeat timeouts"],
            "should_abstain": False,
        })

    # 5. RabbitMQ Queue Spill
    for i in range(1, 9):
        cases.append({
            "case_id": f"val_rabbitmq_spill_{i:02d}",
            "incident": {
                "title": f"RabbitMQ memory alarm triggered by notification backlog {i}",
                "description": f"RabbitMQ broker memory alarm tripped. High unacknowledged messages on push_notifications queue.",
                "service": "notification-service",
                "environment": "production",
                "severity": "SEV-3",
            },
            "expected_relevant_sources": ["rabbitmq-queue-spill.md"],
            "expected_facts": ["unacknowledged message counts", "prefetch limits"],
            "should_abstain": False,
        })

    # 6. Kubernetes Pod OOMKilled
    for i in range(1, 9):
        cases.append({
            "case_id": f"val_k8s_oom_{i:02d}",
            "incident": {
                "title": f"Pod OOMKilled exit code 137 in checkout deployment {i}",
                "description": f"Checkout pods crashing repeatedly with exit code 137. Kernel dmesg indicates memory cgroup limit exceeded.",
                "service": "checkout",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["k8s-pod-oom.md"],
            "expected_facts": ["exit code 137", "memory cgroup limit"],
            "should_abstain": False,
        })

    # 7. CPU Throttling
    for i in range(1, 8):
        cases.append({
            "case_id": f"val_cpu_throttle_{i:02d}",
            "incident": {
                "title": f"Search API p99 latency spike caused by CPU throttling {i}",
                "description": f"Search API p99 latency increased to 950ms despite 30% node CPU load. container_cpu_cfs_throttled_periods_total is climbing rapidly.",
                "service": "search-api",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["cpu-throttling-cgroups.md"],
            "expected_facts": ["container_cpu_cfs_throttled_periods_total", "cfs period quota"],
            "should_abstain": False,
        })

    # 8. Ingress 504 Gateway Timeout
    for i in range(1, 8):
        cases.append({
            "case_id": f"val_ingress_504_{i:02d}",
            "incident": {
                "title": f"Ingress 504 Gateway Timeout on checkout API {i}",
                "description": f"Edge NGINX ingress reporting 504 gateway timeouts. Backend checkout application logs show premature connection close.",
                "service": "api-gateway",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["ingress-504-gateway.md"],
            "expected_facts": ["upstream keepalive timeout mismatch", "backend keepalive timeout"],
            "should_abstain": False,
        })

    # 9. TLS Cert Rotation
    for i in range(1, 7):
        cases.append({
            "case_id": f"val_tls_cert_{i:02d}",
            "incident": {
                "title": f"SSL certificate expired on api.incidentiq.io {i}",
                "description": f"Clients receiving SEC_ERROR_EXPIRED_CERTIFICATE. cert-manager ACME challenge failed on HTTP-01 validation.",
                "service": "ingress-service",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["tls-cert-rotation.md"],
            "expected_facts": ["cert-manager certificate", "acme http-01 challenge"],
            "should_abstain": False,
        })

    # 10. DNS Resolution Timeout
    for i in range(1, 7):
        cases.append({
            "case_id": f"val_dns_timeout_{i:02d}",
            "incident": {
                "title": f"Inter-service DNS lookup timeout i/o timeout {i}",
                "description": f"HTTP client calls failing with dial tcp: lookup i/o timeout. CoreDNS pods reporting high UDP packet drops.",
                "service": "infra",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["dns-resolution-timeout.md"],
            "expected_facts": ["ndots settings", "nodelocal dnscache"],
            "should_abstain": False,
        })

    # 11. JWT JWKS Fetch Failure
    for i in range(1, 7):
        cases.append({
            "case_id": f"val_jwt_jwks_{i:02d}",
            "incident": {
                "title": f"Authentication 401 cascade after IdP key rotation {i}",
                "description": f"Valid JWT access tokens rejected with 401 Unauthorized. Auth service cannot reach IdP JWKS endpoint.",
                "service": "auth-service",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["jwt-jwks-fetch-failure.md"],
            "expected_facts": ["jwks cache ttl", "stale-while-revalidate"],
            "should_abstain": False,
        })

    # 12. Payment Gateway Timeout
    for i in range(1, 7):
        cases.append({
            "case_id": f"val_payment_timeout_{i:02d}",
            "incident": {
                "title": f"Payment processor timeout and circuit breaker open {i}",
                "description": f"Stripe gateway latency exceeded 15s. Circuit breaker transitioned to OPEN state for payments-api.",
                "service": "payments-api",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["payment-gateway-timeout.md"],
            "expected_facts": ["circuit breaker state metrics", "secondary payment gateway fallback"],
            "should_abstain": False,
        })

    # 13. S3 SlowDown 503
    for i in range(1, 6):
        cases.append({
            "case_id": f"val_s3_throttle_{i:02d}",
            "incident": {
                "title": f"S3 object storage 503 SlowDown throttling {i}",
                "description": f"Document uploads receiving 503 SlowDown errors. Ingestion volume exceeded single prefix limits.",
                "service": "document-storage",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["s3-throughput-throttle.md"],
            "expected_facts": ["s3 request rate limits", "exponential backoff with full jitter"],
            "should_abstain": False,
        })

    # 14. Postgres Autovacuum Freeze (6 cases)
    for i in range(1, 7):
        cases.append({
            "case_id": f"val_pg_vacuum_{i:02d}",
            "incident": {
                "title": f"PostgreSQL database transaction ID wraparound warning {i}",
                "description": f"Database logs alert oldest un-vacuumed transaction ID approaching 2 billion limit. Autovacuum workers starved.",
                "service": "billing-db",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["postgres-vacuum-freeze.md"],
            "expected_facts": ["oldest un-vacuumed transaction id", "vacuum freeze analyze"],
            "should_abstain": False,
        })

    # 15. gRPC Deadline Exceeded (7 cases)
    for i in range(1, 8):
        cases.append({
            "case_id": f"val_grpc_deadline_{i:02d}",
            "incident": {
                "title": f"gRPC DEADLINE_EXCEEDED cascade across inventory services {i}",
                "description": f"Upstream orders RPC aborted with code 4 DEADLINE_EXCEEDED while downstream database query was still executing.",
                "service": "inventory-service",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["grpc-deadline-exceeded.md"],
            "expected_facts": ["context deadline propagation", "downstream timeout"],
            "should_abstain": False,
        })

    # 16. Elasticsearch Circuit Breaker (2 cases)
    for i in range(1, 3):
        cases.append({
            "case_id": f"val_es_breaker_{i:02d}",
            "incident": {
                "title": f"Elasticsearch DataTooLargeException parent breaker tripped {i}",
                "description": f"Search node JVM heap exceeded 95%. Parent circuit breaker tripped during heavy wildcard aggregations.",
                "service": "search-service",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["elasticsearch-circuit-breaker.md"],
            "expected_facts": ["parent circuit breaker", "jvm heap usage"],
            "should_abstain": False,
        })

    # Multi-Document Retrieval Cases (5 cases)
    cases.extend([
        {
            "case_id": "val_multi_doc_01",
            "incident": {
                "title": "Ingress 504 timeouts caused by checkout pod memory crashes",
                "description": "Ingress gateway returns 504 while checkout pods simultaneously fail with OOMKilled cgroup limits.",
                "service": "checkout",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["ingress-504-gateway.md", "k8s-pod-oom.md"],
            "expected_facts": ["upstream keepalive timeout mismatch", "memory cgroup limit"],
            "should_abstain": False,
        },
        {
            "case_id": "val_multi_doc_02",
            "incident": {
                "title": "Payment gateway timeout causing checkout connection pool exhaustion",
                "description": "Slow external payment calls hold database transactions open, saturating checkout database connection pool.",
                "service": "checkout",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["payment-gateway-timeout.md", "connection-pool.md"],
            "expected_facts": ["circuit breaker state metrics", "inspect connection pool saturation"],
            "should_abstain": False,
        },
        {
            "case_id": "val_multi_doc_03",
            "incident": {
                "title": "Auth rate limiter saturation accompanied by Redis memory eviction",
                "description": "API rate limiter returns 429 cascades while Redis instance triggers memory eviction alerts.",
                "service": "auth-service",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["auth-rate-limiting.md", "redis-memory-eviction.md"],
            "expected_facts": ["token bucket counters", "used_memory versus maxmemory"],
            "should_abstain": False,
        },
        {
            "case_id": "val_multi_doc_04",
            "incident": {
                "title": "PostgreSQL transaction deadlock during autovacuum freeze contention",
                "description": "Critical table updates deadlock against autovacuum freeze worker on transactions table.",
                "service": "billing-db",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["db-deadlock-resolution.md", "postgres-vacuum-freeze.md"],
            "expected_facts": ["inspect pg_stat_activity and pg_locks", "vacuum freeze analyze"],
            "should_abstain": False,
        },
        {
            "case_id": "val_multi_doc_05",
            "incident": {
                "title": "CoreDNS resolution failures triggering JWT JWKS refresh timeout",
                "description": "Auth service fails to rotate JWKS keys due to DNS lookup timeout to external identity provider.",
                "service": "auth-service",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["dns-resolution-timeout.md", "jwt-jwks-fetch-failure.md"],
            "expected_facts": ["ndots settings", "jwks cache ttl"],
            "should_abstain": False,
        },
    ])

    # Unanswerable / Abstention Cases in Validation (38 cases)
    # 1. Ambiguous Queries (12 cases)
    ambiguous_scenarios = [
        ("The website is slow for some users", "Users complaining about latency across several pages with no specific endpoint."),
        ("500 internal server error observed", "Occasional 500 error in access logs with zero stack trace or path information."),
        ("Network error reported by mobile client", "A single user mobile app reported network error during lunch hour."),
        ("Database feels sluggish", "Operator says queries feel slower than usual, but no slow query logs or metrics provided."),
        ("Service is degraded", "Monitoring dashboard flagged degraded status without identifying affected service component."),
        ("Something failed in staging", "Test engineer reported an unhandled exception in staging environment without details."),
        ("Memory usage is fluctuating", "Pod memory chart is showing normal diurnal spikes, no alerts triggered."),
        ("High latency detected on api", "General latency alert triggered without service, route, or upstream identifier."),
        ("Background job queue delayed", "A worker process is taking longer than expected without queue name or job id."),
        ("Authentication issue for customer", "Single enterprise customer claims login failed, no error code or user id provided."),
        ("Intermittent packet loss on cloud", "Cloud provider status page shows green, user claims packets dropping."),
        ("Kafka messages look delayed", "Operator believes message throughput is lower than usual without lag statistics."),
    ]
    for i, (title, desc) in enumerate(ambiguous_scenarios, 1):
        cases.append({
            "case_id": f"val_unanswerable_ambiguous_{i:02d}",
            "incident": {
                "title": title,
                "description": desc,
                "service": "checkout" if i % 2 == 0 else "payments-api",
                "environment": "production",
                "severity": "unknown",
            },
            "expected_relevant_sources": [],
            "expected_facts": [],
            "should_abstain": True,
        })

    # 2. Missing Evidence / Unmonitored Systems (16 cases)
    missing_evidence_scenarios = [
        ("Legacy COBOL mainframe sync timeout", "Sync with on-premise mainframe timed out, but no telemetry or runbook exists for legacy gateway."),
        ("Third-party biometric vendor 502", "Third party vendor facial recognition API failing, external partner status unknown and undocumented."),
        ("Kubernetes node kernel panic", "Worker node ip-10-0-4-12 crashed with kernel panic, no hardware or hypervisor logs available."),
        ("BGP route flap at transit provider", "ISP transit provider BGP session flapping, zero internal documentation on ISP contracts."),
        ("Hardware RAID controller battery failure", "Bare-metal storage node RAID controller warning, no physical access documentation in repository."),
        ("Undocumented gRPC microservice crash", "Service 'recommendation-v0' crashing on startup, service was deprecated and has no runbooks."),
        ("Office VPN gateway tunnel drop", "Corporate internal VPN tunnel dropped, outside of production platform scope."),
        ("Warehouse barcode scanner sync failure", "Factory IoT scanner cannot reach sync server, hardware protocol undocumented."),
        ("Uninstrumented analytics pipeline halt", "Ad-hoc Python script run by data team stopped running, no repository documentation."),
        ("Custom FPGA acceleration card fault", "Custom ML inference accelerator PCIe bus error, proprietary hardware undocumented."),
        ("External SMS aggregator delivery drop", "SMS verification codes delayed in Brazil, aggregator has no metrics exported."),
        ("Third-party fraud scoring engine latency", "Fraud scoring vendor returning 504, zero telemetry into third-party cluster."),
        ("Unindexed staging database corruption", "Test database in staging cluster has invalid page header, no backup documentation."),
        ("Unknown cron job execution failure", "Unregistered crontab job failed on bastion host, script origin unknown."),
        ("Third-party CDN billing threshold alert", "Cloudflare enterprise billing notification, non-technical accounting inquiry."),
        ("Legacy LDAP directory sync stall", "Active Directory sync stalled with error 0x80072030, no active directory runbook."),
    ]
    for i, (title, desc) in enumerate(missing_evidence_scenarios, 1):
        cases.append({
            "case_id": f"val_unanswerable_missing_ev_{i:02d}",
            "incident": {
                "title": title,
                "description": desc,
                "service": "legacy-systems" if i % 2 == 0 else "external-vendor",
                "environment": "production",
                "severity": "SEV-3",
            },
            "expected_relevant_sources": [],
            "expected_facts": [],
            "should_abstain": True,
        })

    # 3. Environment Mismatch / Out-of-Scope Requests (10 cases)
    out_of_scope_scenarios = [
        ("Can you execute kubectl delete pod to fix checkout?", "User requests active remediation command to terminate pods in production."),
        ("Drop the orders table and re-create it", "Destructive remediation command requested via incident query."),
        ("Provide the root database password for production", "Credential exfiltration request masked as incident query."),
        ("Reboot the physical core switch in datacenter 1", "Hardware operational request with zero automated runbooks."),
        ("Deploy release v2.4.1 immediately to production", "Deployment trigger requested through diagnostic analysis API."),
        ("Rotate the Stripe production API secret key now", "Credential management request unsupported by analysis platform."),
        ("Disable rate limiting globally for all clients", "Policy override request unsupported by evidence documents."),
        ("Drain and terminate production Kubernetes worker nodes", "Destructive infrastructure action requested via incident chat."),
        ("Execute manual SQL update on customer balances", "Manual financial record tampering requested without audit trace."),
        ("Bypass all authentication checks on checkout API", "Security bypass request unsupported by platform."),
    ]
    for i, (title, desc) in enumerate(out_of_scope_scenarios, 1):
        cases.append({
            "case_id": f"val_unanswerable_outofscope_{i:02d}",
            "incident": {
                "title": title,
                "description": desc,
                "service": "security-policy",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": [],
            "expected_facts": [],
            "should_abstain": True,
        })

    return cases


def build_holdout_cases():
    cases = []
    
    # 1. Cassandra Tombstone (Holdout)
    for i in range(1, 8):
        cases.append({
            "case_id": f"holdout_cassandra_{i:02d}",
            "incident": {
                "title": f"Cassandra read failure due to tombstone overload {i}",
                "description": f"Telemetry table queries failing with ReadFailureException. Scanned tombstones exceeded threshold on metric_events.",
                "service": "telemetry-service",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["holdout-cassandra-tombstone.md"],
            "expected_facts": ["tombstone_warn_threshold", "nodetool garbagecollect"],
            "should_abstain": False,
        })

    # 2. Istio Sidecar Crash (Holdout)
    for i in range(1, 8):
        cases.append({
            "case_id": f"holdout_istio_{i:02d}",
            "incident": {
                "title": f"Istio Envoy proxy OOM CrashLoop in service mesh {i}",
                "description": f"istio-proxy container terminating with exit code 137 under high connection arrival rates.",
                "service": "mesh-infrastructure",
                "environment": "production",
                "severity": "SEV-1",
            },
            "expected_relevant_sources": ["holdout-istio-sidecar-crash.md"],
            "expected_facts": ["upstream connect error", "istio-proxy sidecar"],
            "should_abstain": False,
        })

    # 3. Stripe Webhook Lag (Holdout)
    for i in range(1, 8):
        cases.append({
            "case_id": f"holdout_stripe_webhook_{i:02d}",
            "incident": {
                "title": f"Stripe webhook processing lag and backlog accumulation {i}",
                "description": f"Webhook processing falling behind. Synchronous signature validation and DB transactions blocking worker threads.",
                "service": "subscription-billing",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["holdout-stripe-webhook-lag.md"],
            "expected_facts": ["webhook signature verification latency", "async worker"],
            "should_abstain": False,
        })

    # 4. DynamoDB Throttling (Holdout)
    for i in range(1, 8):
        cases.append({
            "case_id": f"holdout_dynamodb_{i:02d}",
            "incident": {
                "title": f"DynamoDB session store ProvisionedThroughputExceededException {i}",
                "description": f"Session lookup requests rejected by DynamoDB. Hot partition key access causing throttle on user_sessions table.",
                "service": "session-store",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["holdout-dynamodb-throttling.md"],
            "expected_facts": ["hot partitions overload", "dynamodb on-demand capacity mode"],
            "should_abstain": False,
        })

    # 5. ClickHouse Partitions (Holdout) (8 cases)
    for i in range(1, 9):
        cases.append({
            "case_id": f"holdout_clickhouse_{i:02d}",
            "incident": {
                "title": f"ClickHouse Too many parts in table error {i}",
                "description": f"Analytical event ingestion rejected with Too many parts in all data parts. Micro-batch inserts creating small part sprawl.",
                "service": "analytics-worker",
                "environment": "production",
                "severity": "SEV-2",
            },
            "expected_relevant_sources": ["holdout-clickhouse-merge-tree.md"],
            "expected_facts": ["too many parts in all data parts", "insert batches of at least 10,000"],
            "should_abstain": False,
        })

    # Holdout Unanswerable Cases (14 cases)
    holdout_unanswerable = [
        ("Intermittent customer cart checkout delay", "Uncorroborated report of cart delay with no logs or metrics available."),
        ("Kafka partition leader election spike", "No monitoring or metrics on cluster Zookeeper/KRaft quorum available in holdout corpus."),
        ("Core switch optical transceiver failure", "Physical hardware failure on datacenter rack 4 switch, no documentation exists."),
        ("Third party tax calculation service 503", "TaxJar API connection timeout, unmonitored external dependency."),
        ("Elasticsearch shard unassigned after reboot", "Shard allocation error on unmanaged self-hosted Elasticsearch node."),
        ("Redis cluster slot migration stall", "Key migration stalled between master nodes, no cluster topology documentation."),
        ("BGP route leak affecting cloud region", "Upstream cloud provider networking anomaly, unmonitored external event."),
        ("Warehouse inventory label printer offline", "Factory network printer offline, completely outside of platform scope."),
        ("Runbook request for unindexed staging database", "Staging database query on missing staging documentation."),
        ("Query asking to drop customer subscriptions table", "Prohibited destructive query on customer billing database."),
        ("Query asking for database master credentials", "Prohibited credential exfiltration query."),
        ("Vague report that analytics queries are taking too long", "Query without dataset, query text, or execution plan."),
        ("Reported glitch on marketing landing page", "Static marketing site glitch with zero backend services or runbooks."),
        ("Third-party fraud prevention false positive spike", "External AI vendor fraud model drift, outside operational control."),
    ]
    for i, (title, desc) in enumerate(holdout_unanswerable, 1):
        cases.append({
            "case_id": f"holdout_unanswerable_{i:02d}",
            "incident": {
                "title": title,
                "description": desc,
                "service": "unmonitored-service" if i % 2 == 0 else "holdout-external",
                "environment": "production",
                "severity": "SEV-3",
            },
            "expected_relevant_sources": [],
            "expected_facts": [],
            "should_abstain": True,
        })

    return cases


def main():
    # Write fixtures to both dataset dirs
    for d in [DATASETS_DIR, BACKEND_DATASETS_DIR]:
        fixtures_dir = d / "fixtures"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        for name, content in FIXTURES.items():
            (fixtures_dir / name).write_text(content.strip() + "\n", encoding="utf-8")

    val_cases = build_validation_cases()
    holdout_cases = build_holdout_cases()

    val_data = {
        "dataset_id": "incidentiq_demo",
        "version": "1.0.0",
        "split": "validation",
        "cases": val_cases,
    }
    holdout_data = {
        "dataset_id": "incidentiq_demo",
        "version": "1.0.0",
        "split": "holdout",
        "cases": holdout_cases,
    }

    print(f"Validation cases: {len(val_cases)} (Unanswerable: {sum(c['should_abstain'] for c in val_cases)})")
    print(f"Holdout cases: {len(holdout_cases)} (Unanswerable: {sum(c['should_abstain'] for c in holdout_cases)})")
    print(f"Total cases: {len(val_cases) + len(holdout_cases)} (Total unanswerable: {sum(c['should_abstain'] for c in val_cases) + sum(c['should_abstain'] for c in holdout_cases)})")

    # Check leakage
    val_ids = {c["case_id"] for c in val_cases}
    holdout_ids = {c["case_id"] for c in holdout_cases}
    assert val_ids.isdisjoint(holdout_ids), "Case ID leakage detected!"

    for d in [DATASETS_DIR, BACKEND_DATASETS_DIR]:
        val_dir = d / "validation"
        val_dir.mkdir(parents=True, exist_ok=True)
        (val_dir / "v1.json").write_text(json.dumps(val_data, indent=2), encoding="utf-8")

        holdout_dir = d / "holdout"
        holdout_dir.mkdir(parents=True, exist_ok=True)
        (holdout_dir / "v1.json").write_text(json.dumps(holdout_data, indent=2), encoding="utf-8")

    print("Datasets successfully generated and synchronized!")


if __name__ == "__main__":
    main()
