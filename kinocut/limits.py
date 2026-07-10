"""Resource limits and validation constants for Kinocut."""

# Video limits
MAX_VIDEO_DURATION = 14400  # 4 hours in seconds
MAX_RESOLUTION = 7680  # 8K width/height
MAX_FILE_SIZE_MB = 4096  # 4 GB

# Processing limits
DEFAULT_FFMPEG_TIMEOUT = 600  # 10 minutes
DEFAULT_AI_TIMEOUT = 3600  # 1 hour for AI operations (demucs, whisper, etc.)
DOCTOR_COMMAND_TIMEOUT = 10  # Short version/probe commands should not hang
FFPROBE_TIMEOUT = 30  # Metadata probes should fail quickly
QUALITY_GUARDRAILS_TIMEOUT = 120  # Quality check commands
MAX_BATCH_SIZE = 50
MAX_EXPORT_FRAMES_FPS = 60
MAX_AI_SCENE_FRAMES = 600
MAX_AI_UPSCALE_FRAMES = 1800
MAX_MOGRAPH_FRAMES = 1800

# Audio limits
MAX_AUDIO_DURATION = 3600  # 1 hour
MAX_AI_TRANSCRIBE_DURATION = MAX_AUDIO_DURATION
MIN_FREQUENCY = 20  # Human hearing lower bound
MAX_FREQUENCY = 20000  # Human hearing upper bound
MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 96000

# Numeric parameter bounds
MIN_SPEED_FACTOR = 0.01
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

# Workflow-engine bounds (fail closed above these)
MAX_WORKFLOW_STEPS = 64
MAX_WORKFLOW_VARIANTS = 32
