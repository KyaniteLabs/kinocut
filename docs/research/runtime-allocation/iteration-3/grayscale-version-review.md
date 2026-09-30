# Grayscale signal-domain verification

FFprobe 6.1 was built from the official FFmpeg `n6.1` source at
`d4ff0020b40b524a490cf62eccbd3a318f4c0e58`, with network support disabled.
The minimal build included FFV1/rawvideo decoding, lavfi and `wrapped_avframe`.
The comparison retained system FFmpeg 7.1.5 for fixture creation and the FFmpeg
fallback, while selecting FFprobe 6.1 or 7.1.5 for native measurements. This is a
converter comparison, not a claim that the minimal binary passed every feature.

Before repair, FFprobe 6.1 reproduced the hosted grayscale YMIN assertion:
43.125 versus 52.92941176470588. Output-range settings alone did not fix it.
Explicit full-range gray input did. The repair applies `setparams=range=full`
only to gray sources, matching existing 8-bit behavior even with TV metadata;
ordinary YUV retains its own sample range. Ambiguous mixed gray/color video
streams yield unavailable measurements rather than applying the wrong policy.

The [matrix](grayscale-version-matrix.json) covers 48 real lossless fixtures:
32 moving gray/YUV420/YUV422/YUV444 sources across 8/10/12/16 bits and TV/PC
metadata, plus 16 static gray/YUV422/YUV444 controls. Each of the 96 measurement
sets exercises batch tags, individual YAVG, fallback YAVG and temporal motion.
The [script](grayscale-version-matrix.py) reproduces the comparison after preparing
both FFprobe binaries. Run from the repository root:

```sh
PYTHONPATH=. .venv/bin/python docs/research/runtime-allocation/iteration-3/grayscale-version-matrix.py --ffprobe6 /path/to/prepared/ffprobe6 --output /path/to/matrix.json
```

The script creates an isolated binary-selection directory and restores PATH.
Binary paths are prerequisites, not shipped tools.

| Check | Maximum observed error | Required bound |
| --- | ---: | ---: |
| Native YUV cross-version tags | 0 | 0.001 |
| Gray cross-version tags | 0.61523 | 1 |
| Gray absolute YMIN | 0.13993 | 0.2 |
| Individual versus batch YAVG | 0 | 0.001 |
| Fallback versus batch YAVG | 0.38798 | 0.6 |
| Gray motion amplitude | 0.00892 | 0.2 |

All 16 static controls have zero motion and static fraction 1. The 29 original
signal-domain tests also passed with FFprobe 6.1 in 5.46 seconds. Test tolerances
were not loosened. New absolute gray anchors and source-metadata failure/cache
checks cover the scoped repair. Frozen source/full-suite evidence follows in the
[PR validation record](../../PR_VALIDATION.md).

The related upstream [swscale range reinitialization repair](https://github.com/FFmpeg/FFmpeg/commit/d043e5c54c3f8e98be1a4bc1bcb76407af0e8ac7)
supports investigating older range conversion. No commit bisect was performed;
it is not identified as the sole cause. Filesystem cache identity is not an
immutable input snapshot, and SDR measurements do not evaluate HDR acceptance.
