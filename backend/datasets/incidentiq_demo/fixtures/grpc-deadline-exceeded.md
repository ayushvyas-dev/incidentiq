# gRPC DEADLINE_EXCEEDED Cascade Across Microservices

When client calls fail with DEADLINE_EXCEEDED (status code 4), verify context deadline propagation across internal RPC hops. Missing context deadline subtraction causes upstream timeouts while downstream work continues needlessly. Ensure deadline propagation and set aggressive client timeouts.
