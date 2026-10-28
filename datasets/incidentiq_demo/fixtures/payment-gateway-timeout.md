# Payment Gateway Latency and Circuit Breaker Tripping

When checkout transactions fail with payment gateway timeout, inspect circuit breaker state metrics for payment-service. Verify whether error threshold tripped the breaker into OPEN state. Check secondary payment gateway fallback health and switch traffic routing to backup acquirer.
