# AWS S3 503 SlowDown and Partition Key Hotspotting

When object storage uploads or downloads receive HTTP 503 SlowDown responses, verify S3 request rate limits (3,500 PUT/5,500 GET per second per prefix). Implement hash-based prefix partitioning for object keys. Apply exponential backoff with full jitter in the storage client SDK.
