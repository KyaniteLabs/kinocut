"""Pydantic result models for image analysis tools."""

from __future__ import annotations

from pydantic import BaseModel


class DominantColor(BaseModel):
    """A single dominant color extracted from an image."""

    hex: str  # "#8B4513"
    rgb: tuple[int, int, int]  # (139, 69, 19)
    name: str  # "saddlebrown"
    percentage: float  # 34.2


class ColorExtractionResult(BaseModel):
    """Result of extracting dominant colors from an image."""

    success: bool = True
    image_path: str
    colors: list[DominantColor]
    n_colors: int


class PaletteColor(BaseModel):
    """A single color in a generated palette."""

    hex: str
    rgb: tuple[int, int, int]
    role: str  # "base", "complement", "accent1", "accent2", etc.


class PaletteResult(BaseModel):
    """Result of generating a color harmony palette."""

    success: bool = True
    image_path: str
    harmony: str
    palette: list[PaletteColor]
    source_color: DominantColor


class ProductAnalysisResult(BaseModel):
    """Result of analyzing a product image."""

    success: bool = True
    image_path: str
    colors: list[DominantColor]
    description: str | None = None
    ai_description: bool = False
