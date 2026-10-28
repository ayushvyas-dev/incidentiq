# Ingress 504 Gateway Timeout and Upstream Keepalive

When edge ingress proxies return 504 Gateway Timeout, inspect upstream keepalive timeout mismatch between proxy and backend server. If backend keepalive timeout is shorter than proxy keepalive timeout, proxy sends requests to closing connections. Set backend keepalive timeout at least 5 seconds higher than proxy.
