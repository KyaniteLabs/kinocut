"""Kinocut Python client image operations."""

from __future__ import annotations


class ClientImageMixin:
    """Image operations mixin."""

    def extract_colors(
        self,
        image_path: str,
        n_colors: int = 5,
    ) -> dict:
        """Extract dominant colors from an image using K-means clustering."""
        from ..image_engine import extract_colors

        return extract_colors(image_path, n_colors=n_colors)

    def generate_palette(
        self,
        image_path: str,
        harmony: str = "complementary",
        n_colors: int = 5,
    ) -> dict:
        """Generate a color harmony palette from an image's dominant color."""
        from ..image_engine import generate_palette

        return generate_palette(image_path, harmony=harmony, n_colors=n_colors)

    def analyze_product(
        self,
        image_path: str,
        use_ai: bool = False,
        n_colors: int = 5,
    ) -> dict:
        """Analyze a product image — extract colors and optionally generate AI description."""
        from ..image_engine import analyze_product

        return analyze_product(image_path, use_ai=use_ai, n_colors=n_colors)

    def still_match(
        self,
        hero: str,
        inputs: list[str],
        output_dir: str,
    ) -> dict:
        """Match stills to a hero plate with shared WB/exposure gains."""
        from ..still_plates import still_match

        return still_match(hero=hero, inputs=inputs, output_dir=output_dir)

    def still_grade(
        self,
        inputs: list[str],
        output_dir: str,
        hero: str | None = None,
        lut_path: str | None = None,
        signal_mode: bool = False,
    ) -> dict:
        """Ordered still grade: correct→match→look (optional LUT last)."""
        from ..still_plates import still_grade

        return still_grade(
            inputs=inputs,
            output_dir=output_dir,
            hero=hero,
            lut_path=lut_path,
            signal_mode=signal_mode,
        )

    def still_gate(self, inputs: list[str], output_dir: str) -> dict:
        """Fail-closed cohesion gate + contact sheet for a still package."""
        from ..still_plates import still_gate

        return still_gate(inputs=inputs, output_dir=output_dir)

    def image_edit(
        self,
        source: str,
        reference: str,
        intent: str,
        output_dir: str,
        prefer: str = "edit",
        allow_paid_gen: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """Free establish-locked still edit with plan/receipt."""
        from ..still_plates import image_edit

        return image_edit(
            source=source,
            reference=reference,
            intent=intent,
            output_dir=output_dir,
            prefer=prefer,
            allow_paid_gen=allow_paid_gen,
            dry_run=dry_run,
        )

    def still_package(
        self,
        establish: str,
        beats: list[str],
        output_dir: str,
        dry_run: bool = False,
        apply_grade: bool = True,
        lut_path: str | None = None,
        signal_mode: bool = False,
    ) -> dict:
        """Package workflow: edit beats → match → grade → gate."""
        from ..still_plates import still_package

        return still_package(
            establish=establish,
            beats=beats,
            output_dir=output_dir,
            dry_run=dry_run,
            apply_grade=apply_grade,
            lut_path=lut_path,
            signal_mode=signal_mode,
        )
