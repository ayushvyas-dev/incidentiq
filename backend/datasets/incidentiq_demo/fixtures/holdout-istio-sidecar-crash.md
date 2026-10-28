# Istio Envoy Sidecar Out of Memory CrashLoop

When application pods report upstream connect error or Envoy proxy crashes, inspect proxy_init and istio-proxy container exit codes. High inbound connection rates or large xDS route clusters cause Envoy memory exhaustion. Allocate higher memory limit to istio-proxy sidecar.
