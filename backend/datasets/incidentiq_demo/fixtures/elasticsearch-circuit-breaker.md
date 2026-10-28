# Elasticsearch DataTooLargeException and Fielddata Breaker

When log search or document query fails with DataTooLargeException, inspect Elasticsearch JVM heap usage and parent circuit breaker statistics. Avoid running unconstrained wildcard aggregations on analyzed text fields. Increase indices.breaker.total.use_real_memory threshold.
