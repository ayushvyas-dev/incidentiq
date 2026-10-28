# API Rate Limiter Saturation and 429 Cascades

When legitimate client requests receive 429 Too Many Requests, inspect Redis token bucket counters and IP reputation tiers. Check if corporate proxies or shared NAT gateways share IP rate limit buckets. Configure authenticated user rate limiting by customer ID rather than client IP.
