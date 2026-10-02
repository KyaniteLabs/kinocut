"""Resource limits and validation constants for Kinocut."""

# Video limits
MAX_VIDEO_DURATION = 14400  # 4 hours in seconds
MAX_RESOLUTION = 7680  # 8K width/height
MAX_FILE_SIZE_MB = 4096  # 4 GB
YOUTUBE_SHORTS_MAX_DURATION_SECONDS = 180.0
INSTAGRAM_REELS_MAX_DURATION_SECONDS = 90.0
MIN_SHORTS_PREVIEW_DURATION_SECONDS = 1.0

# Processing limits
DEFAULT_FFMPEG_TIMEOUT = 600  # 10 minutes
FFMPEG_STDERR_DIAGNOSTIC_BYTES = 4096  # Read at most this much from redirected failure logs.
FFMPEG_PROGRESS_READ_BYTES = 4096
FFMPEG_PROGRESS_STDERR_BYTES = 65_536
FFMPEG_PROGRESS_LINE_BYTES = 4096
SUBPROCESS_READ_CHUNK_BYTES = 65_536
MAX_SUBPROCESS_STDOUT_BYTES = 16 * 1024 * 1024
MAX_SUBPROCESS_STDERR_BYTES = 4 * 1024 * 1024
MAX_FFMPEG_PIPE_BYTES = 128 * 1024 * 1024
MAX_PROCESS_GUARDIAN_ERROR_BYTES = 256
DEFAULT_AI_TIMEOUT = 3600  # 1 hour for AI operations (demucs, whisper, etc.)
DOCTOR_COMMAND_TIMEOUT = 10  # Short version/probe commands should not hang
FFPROBE_TIMEOUT = 30  # Metadata probes should fail quickly
QUALITY_GUARDRAILS_TIMEOUT = 120  # Quality check commands
MAX_BATCH_SIZE = 50
MAX_EXPORT_FRAMES_FPS = 60
MAX_AI_SCENE_FRAMES = 600
MAX_AI_UPSCALE_FRAMES = 1800
MAX_OBJECT_MATTE_FRAMES = 3600
MAX_OBJECT_MATTE_SCRATCH_BYTES = 4 * 1024 * 1024 * 1024
MAX_OBJECT_MATTE_EQUIPMENT_SAMPLES = 60
MAX_MOGRAPH_FRAMES = 1800
MAX_TEMPORAL_INSPECTION_FRAMES = 18000
MAX_INSPECTION_LINEAGE_JSON_BYTES = 65_536
MAX_INSPECTION_DECLARED_REGIONS = 32
MAX_WAVE3_JSON_BYTES = 65_536
MAX_REVIDEO_JOB_JSON_BYTES = 1_048_576
MAX_WAVE3_VERDICT_IDS = 64
MAX_WAVE3_AUTH_DECISION_IDS = 64
MAX_ACCEPTANCE_EVIDENCE_FILES = 64
MAX_ESTIMATE_OPERATION_CHARS = 128

# Long-form transcription chunking (per-chunk cap and overlap for the
# reusable long-form stream-to-shorts workflow). These are independent of
# MAX_AI_TRANSCRIBE_DURATION: ordinary ai_transcribe still rejects >3600s,
# while transcribe_longform permits media up to MAX_VIDEO_DURATION.
MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS = 1500  # 25 minutes per chunk
LONGFORM_TRANSCRIBE_OVERLAP_SECONDS = 15  # tail-overlap for word dedup
MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS = 30  # refuse sub-30s windows
MAX_LONGFORM_TRANSCRIBE_CHUNKS = 64  # upper bound on plan size

# Audio limits
MAX_AUDIO_DURATION = 3600  # 1 hour
MAX_AI_TRANSCRIBE_DURATION = MAX_AUDIO_DURATION
MIN_FREQUENCY = 20  # Human hearing lower bound
MAX_FREQUENCY = 20000  # Human hearing upper bound
MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 96000

# Numeric parameter bounds
MIN_SPEED_FACTOR = 0.01
MIN_AUDIO_BED_LOOP_CROSSFADE_SECONDS = 0.0
MAX_AUDIO_BED_LOOP_CROSSFADE_SECONDS = 30.0
MIN_AUDIO_BED_FADE_SECONDS = 0.0
MAX_AUDIO_BED_FADE_SECONDS = 30.0
MIN_AUDIO_BED_TARGET_LUFS = -70.0
MAX_AUDIO_BED_TARGET_LUFS = -5.0
MIN_AUDIO_BED_DUCK_THRESHOLD = 0.001
MAX_AUDIO_BED_DUCK_THRESHOLD = 1.0
MIN_AUDIO_BED_DUCK_RATIO = 1.0
MAX_AUDIO_BED_DUCK_RATIO = 20.0
MIN_AUDIO_BED_DUCK_ATTACK_MS = 1.0
MAX_AUDIO_BED_DUCK_ATTACK_MS = 2000.0
MIN_AUDIO_BED_DUCK_RELEASE_MS = 1.0
MAX_AUDIO_BED_DUCK_RELEASE_MS = 9000.0
MIN_AUDIO_BED_MUSIC_VOLUME = 0.0
MAX_AUDIO_BED_MUSIC_VOLUME = 2.0
MIN_AUDIO_BED_DURATION_TOLERANCE_SECONDS = 0.0
MAX_AUDIO_BED_DURATION_TOLERANCE_SECONDS = 30.0
MAX_SPEED_FACTOR = 100.0

# Encoding parameter bounds
MAX_CRF = 51
MIN_CRF = 0
DEFAULT_CRF = 23
DEFAULT_PRESET = "fast"

# Network / concurrency bounds
MAX_PORT = 65535
MIN_PORT = 1
MAX_CONCURRENCY = 16

# Processing bounds
MAX_SPEED_CHAIN_COUNT = 20

# Revideo bridge runtime floor. Must match the "node" engines floor declared
# by npm/package.json (the mcpb launcher) and the vendored bridge template's
# puppeteer/vite dependency engines; RevideoNotFoundError names it verbatim.
REVIDEO_NODE_MAJOR_MIN = 18
REVIDEO_TIMEOUT_MAX_SECONDS = 2_147_483_647

# Workflow-engine bounds (fail closed above these)
MAX_WORKFLOW_STEPS = 64
MAX_WORKFLOW_VARIANTS = 32

# Graphics composition bounds (receipt-bound editor layer stack).
MAX_GRAPHICS_LAYERS = 32
MAX_GRAPHICS_CANVAS_DURATION = 60.0  # seconds; protects the receipt output window

# Bounds for a single multi-track audio mixing graph.
MAX_AUDIO_MIX_TRACKS = 64
MAX_AUDIO_MIX_VOLUME = 4.0
MIN_AUDIO_MIX_BITRATE_KBPS = 8
MAX_AUDIO_MIX_BITRATE_KBPS = 512
MAX_AUDIO_MIX_TIMELINE_PACKETS = 1_000_000
MAX_AUDIO_MIX_TIMELINE_METADATA_BYTES = 64 * 1024 * 1024

# All-frame quality analysis resource ceilings; exceeding them is unavailable, never partial success.
MAX_QUALITY_SIGNALSTATS_FRAMES = 1_000_000
MAX_QUALITY_SIGNALSTATS_LINE_BYTES = 4096
MAX_QUALITY_SIGNALSTATS_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_QUALITY_SIGNALSTATS_DIAGNOSTIC_BYTES = 65536

# Hard bounds for executed semantic vision requests and results.
MAX_VISION_SAMPLE_FRAMES = 12
MAX_VISION_KEYFRAME_BYTES = 2 * 1024 * 1024
MAX_VISION_RESPONSE_BYTES = 64 * 1024

MAX_FONT_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_FONT_IDENTIFIER_CHARACTERS = 4096
MAX_FONT_TABLES = 256
MAX_FONT_COLLECTION_FONTS = 64
MAX_FONT_DOWNLOAD_READ_BYTES = 65536
MAX_FONT_DOWNLOAD_DIAGNOSTIC_BYTES = 65536

# Base64 images plus bounded schema/prompt overhead for one semantic request.
MAX_VISION_REQUEST_BYTES = MAX_VISION_SAMPLE_FRAMES * MAX_VISION_KEYFRAME_BYTES * 4 // 3 + MAX_VISION_RESPONSE_BYTES

# Bound both dimensions of scene thumbnails, including extreme aspect ratios.
MAX_AI_SCENE_FRAME_WIDTH = 320
MAX_AI_SCENE_FRAME_HEIGHT = 1920

# CI-only Hyperframes execution evidence; not a media or provider payload cap.
MAX_CI_HYPERFRAMES_REPORT_BYTES = 64 * 1024

# Serialized track descriptions accepted by audio mixing operator adapters.
MAX_AUDIO_MIX_JSON_BYTES = 65_536

# JSON file admission limits for local operator planning and review routes.
MAX_CLI_JSON_ARTIFACT_BYTES = 1_048_576
# Motion producer: at most duration+1 one-second windows, three findings per
# window plus copied review items, and frame-bounded transitions/gaps. These
# conservative wire budgets cover compact and standard indent=2 JSON, including
# finite float representations and fixed schema keys. Keep in sync with the
# producer's window width/fields; arbitrary padding is intentionally bounded.
MAX_MOTION_REPORT_JSON_BYTES = 65_536 + (MAX_VIDEO_DURATION + 1) * 3072 + MAX_TEMPORAL_INSPECTION_FRAMES * 1024
# Each disposition contains a fixed SHA-256 review ID and a closed short value;
# watched intervals contain two bounded finite numbers. Allow formatting slack.
MAX_MOTION_DISPOSITIONS_JSON_BYTES = 4096 + 3 * MAX_TEMPORAL_INSPECTION_FRAMES * 128
MAX_MOTION_WATCHED_INTERVALS_JSON_BYTES = 4096 + MAX_TEMPORAL_INSPECTION_FRAMES * 128
MAX_POST_RESCUE_REQUEST_BYTES = 4_194_304
MAX_JSON_ARTIFACT_DEPTH = 128
