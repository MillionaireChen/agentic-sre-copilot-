# Memory Leak

## Symptoms

- `process_resident_memory_bytes` grows monotonically over minutes/hours
- GC pause duration increases as the heap fills
- workers terminated with OOM, `container_restart_count_total` increasing
- latency degrades in a sawtooth pattern following restarts

## Investigation

1. Plot memory usage over the last hour; confirm monotonic growth.
2. Check restart counts and OOM kill messages in logs.
3. Correlate leak onset with recent deployments.
4. Identify the leaking component from heap profiles if available.

## Remediation

- Temporary mitigation: restart the affected service to reclaim memory
  (requires approval). This does not fix the leak.
- Preferred remediation: roll back the deployment that introduced the leak
  (requires approval).
