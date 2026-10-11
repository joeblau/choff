# CI soak collector comparison

[Run 38094802292](https://github.com/joeblau/voice/actions/runs/38094802292)
uses source `26b765859a65695fcf22fb0a114cc0a98746ccf3`, except for a
diagnostic workflow. The app, package, and soak sources also match `296e664`;
that later commit changes only settings UI-test synchronization.

The same CI host and iPhone 17 simulator run three consecutive phases:
without external leak scans, with the existing collector, then without scans
again. Each phase runs `make soak SOAK_MINUTES=20 SOAK_SPEED=10
SOAK_ASR=scripted`, with parallel testing and test-diagnostic collection
disabled. Only `SOAK_LEAKS` changes between phases. All original checks,
sampling, warmup exclusion, and the 2 MB/hour threshold remain unchanged.

| Phase | Footprint slope | Live-heap slope | First audio, early → late | Checks |
| --- | ---: | ---: | --- | --- |
| Unprofiled first | +0.96 MB/hour | +1.46 MB/hour | 65.5 → 64.8 ms | 8/8 pass |
| Scanned | +0.00 MB/hour | +1.63 MB/hour | 64.7 → 64.7 ms | 8/8 pass |
| Unprofiled last | +0.75 MB/hour | +1.62 MB/hour | 64.1 → 64.1 ms | 8/8 pass |

Each phase plays 1,204.22 seconds of audio at 10× speed, answers all 45
utterances, delivers 60,211 frames with zero drops, and renews and reseeds
once. There are six topic boundaries for seven scripted topic changes.
The scanned phase records three identical readings: 55 leaks / 1,760 bytes,
at collector wall times 92, 162, and 207 seconds.

The reports pass; the workflow's success alone is not the evidence. The
`soak-collector-control` artifact retains each report, samples, result bundle,
build/test log, exit status, and the scanned phase's leak output.

The preceding [run 38091996194](https://github.com/joeblau/voice/actions/runs/38091996194)
failed footprint slope (+7.11 MB/hour) and first-audio drift (65.2 → 158.2 ms)
on a different CI host. Its live-heap slope was +1.30 MB/hour. This comparison
does not establish why that run failed or that external scans caused it.
The existing collector and all thresholds are retained. These scripted
simulator results do not establish physical-device or real-model acceptance.
