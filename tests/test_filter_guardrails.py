"""Tests for filter_guardrails module."""


from mcp_video.filter_guardrails import validate_filter_params, clamp_filter_params


class TestValidateFilterParams:
    def test_blur_radius_in_range_clean(self):
        assert validate_filter_params("blur", {"radius": 5.0}) == []

    def test_blur_radius_too_high_warns(self):
        warnings = validate_filter_params("blur", {"radius": 100.0})
        assert any("outside recommended range" in w for w in warnings)

    def test_blur_radius_negative_warns(self):
        warnings = validate_filter_params("blur", {"radius": -1.0})
        assert any("outside recommended range" in w for w in warnings)

    def test_unknown_filter_no_warnings(self):
        assert validate_filter_params("unknown_filter", {"foo": 999}) == []

    def test_brightness_extreme_warns(self):
        warnings = validate_filter_params("brightness", {"level": 10.0})
        assert len(warnings) == 1

    def test_empty_params_clean(self):
        assert validate_filter_params("blur", {}) == []

    def test_non_numeric_param_warns(self):
        warnings = validate_filter_params("blur", {"radius": "big"})
        assert any("must be numeric" in w for w in warnings)

    def test_denoise_bounds(self):
        assert validate_filter_params("denoise", {"luma_spatial": 4.0}) == []
        warnings = validate_filter_params("denoise", {"luma_spatial": 50.0})
        assert len(warnings) == 1


class TestClampFilterParams:
    def test_blur_radius_clamped_high(self):
        result = clamp_filter_params("blur", {"radius": 100.0})
        assert result["radius"] == 50.0

    def test_blur_radius_clamped_low(self):
        result = clamp_filter_params("blur", {"radius": -5.0})
        assert result["radius"] == 0.0

    def test_unbounded_param_unchanged(self):
        result = clamp_filter_params("unknown", {"x": 999})
        assert result["x"] == 999

    def test_in_range_unchanged(self):
        result = clamp_filter_params("blur", {"radius": 5.0, "strength": 2.0})
        assert result["radius"] == 5.0
        assert result["strength"] == 2.0

    def test_original_dict_not_mutated(self):
        original = {"radius": 100.0}
        clamp_filter_params("blur", original)
        assert original["radius"] == 100.0
