# Database connection pool

When acquisition timeouts rise, inspect connection pool saturation and connection leaks. Compare active connections with the configured pool size before changing pool settings. Check for unclosed transactions and long-running queries holding idle-in-transaction locks.
