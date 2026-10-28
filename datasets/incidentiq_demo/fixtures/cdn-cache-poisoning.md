# CDN 502 Error Caching and Emergency Cache Purge

When CDN edge nodes serve cached 502 Bad Gateway responses after upstream service recovery, inspect Cache-Control headers on origin error responses. Ensure origin sets Cache-Control: no-cache, no-store for 5xx errors. Trigger targeted CDN tag-based cache purge.
