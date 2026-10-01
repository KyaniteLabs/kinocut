"""Client operations for image, luminance, and geometric masks."""

from ..engine import apply_mask as _apply_mask, luma_key as _luma_key, shape_mask as _shape_mask
from ..models import EditResult


class ClientMasksMixin:
    """Preserve the mask family across canonical and compatibility clients."""

    def apply_mask(
        self,
        video: str,
        mask: str,
        feather: int = 5,
        output: str | None = None,
    ) -> EditResult:
        """Apply an image mask to a video with edge feathering."""
        return _apply_mask(video, mask_path=mask, feather=feather, output_path=output)

    def luma_key(
        self,
        video: str,
        threshold: float = 0.5,
        output: str | None = None,
    ) -> EditResult:
        """Mask out dark regions based on luminance (brightness)."""
        return _luma_key(video, threshold=threshold, output_path=output)

    def shape_mask(
        self,
        video: str,
        shape: str = "circle",
        output: str | None = None,
        feather: int = 0,
    ) -> EditResult:
        """Apply a geometric shape mask (circle, rounded_rect, oval)."""
        return _shape_mask(video, shape=shape, output_path=output, feather=feather)
