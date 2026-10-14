# Supplemental Jev vs. v1 timing comparison

Run: `jev-1.13-575af3c7e3bf`

Dataset revision: `50d9db968aaeca0acd7d895bed8181bc07c98363`

## Paired timing results

| Measure | Same-row n | Median | Mean | p90 |
|---|---:|---:|---:|---:|
| v1 quorum: sum of three sequential judge latencies | 768 | 49.908 s | 65.153 s | 106.335 s |
| Jev: completion interval less the 200 ms pacing delay | 768 | 0.1968 s | 0.2019 s | 0.2341 s |

The ratio of the two medians is **253.6×**. Treat this as an indicative wall-time comparison, not a service-latency benchmark.

The archived v1 panel store contains 770 matched panels with all three individual `latency_ms` values. The same-row Jev timing comparison covers 768 of those rows: one result was resumed without a new Jev call, and the first live Jev call after that resume has no preceding in-run completion timestamp from which to derive an interval.

## Individual v1 judge call latency

These per-model statistics use all 770 matched archived panel records, not only the 768-row timing intersection.

| Judge model | n | Median | Mean | p90 |
|---|---:|---:|---:|---:|
| `openrouter/openai/gpt-5.6-sol` | 770 | 5.32 s | 6.51 s | 11.35 s |
| `openrouter/z-ai/glm-5.2` | 770 | 10.18 s | 17.66 s | 29.73 s |
| `openrouter/moonshotai/kimi-k3` | 770 | 31.95 s | 40.91 s | 69.31 s |

## Measurement and limitations

- The v1 harness records `VerdictRecord.latency_ms` from immediately before each judge call until a schema-valid response is accepted. `judge_panel()` awaits the three calls sequentially. Summing their per-call latencies approximates the time for one quorum pass; small Python and file-write overhead between calls is not included.
- Jev does not record per-request latency. Its estimate is the gap between consecutive `completed_at` timestamps minus the configured 200 ms inter-request delay. The remaining interval includes request preparation and local output/progress writing as well as the Jev request; it is not pure API latency.
- The v1 source JSONL contains panel labels but no individual latency fields. Timings were extracted from the archived EC2 `results/panel-verdicts` store and matched by trajectory ID and majority label. All 770 paired rows had three recorded judge latencies.
- No per-trajectory timing records or raw judge verdicts are included in this PR. Only aggregate statistics and fingerprints are published. The local timing sidecar remains under the ignored `results/` directory.
- The reported p90 is the sorted sample value at index `floor(0.9 * (n - 1))`.

- Timing extract SHA-256 (770 v1 panels): `509227a8e1c0b1465778c43f5bcb69ee91113edb694803fe1d6ce9b217ccc793`
- Matched timing-pair SHA-256 (768 same-row pairs): `062077cc2dd54f8569560a6ffbfdc41947c7fad11e1153ad2a778f80db4f9c14`
