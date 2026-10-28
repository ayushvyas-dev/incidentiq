# Stripe Webhook Processing Lag and Signature Verification

When billing webhook handler falls behind event arrival rate, inspect webhook signature verification latency and Redis job queue depth. Long database transactions in webhook thread pool block incoming deliveries. Separate webhook ingestion from processing with an async worker.
