"""Visual Design Quality System for mcp-video.

Comprehensive design quality checks that go beyond technical metrics
to evaluate visual hierarchy, layout, typography, spacing, and motion design.
Includes auto-fix capabilities.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal


logger = logging.getLogger(__name__)


@dataclass
class DesignIssue:
    """A design quality issue with severity and fix recommendation."""

    category: str  # 'layout', 'typography', 'color', 'motion', 'composition', 'hierarchy', 'timing'
    severity: Literal["error", "warning", "info"]
    message: str
    frame: int | None = None
    fix_available: bool = False
    auto_fix: Callable | None = None
    fix_description: str = ""


@dataclass
class DesignQualityReport:
    """Comprehensive design quality report."""

    video_path: str
    overall_score: float  # 0-100
    technical_score: float  # brightness, contrast, etc
    design_score: float  # layout, typography, etc
    hierarchy_score: float  # visual hierarchy
    motion_score: float  # animation quality
    issues: list[DesignIssue] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def get_errors(self) -> list[DesignIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def get_warnings(self) -> list[DesignIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def has_fixable_issues(self) -> bool:
        return any(i.fix_available for i in self.issues)

    def get_score_breakdown(self) -> dict:
        """Get detailed score breakdown with improvement potential."""
        return {
            "technical": {
                "score": self.technical_score,
                "weight": 0.25,
                "potential": 100 - self.technical_score,
            },
            "design": {
                "score": self.design_score,
                "weight": 0.25,
                "potential": 100 - self.design_score,
            },
            "hierarchy": {
                "score": self.hierarchy_score,
                "weight": 0.25,
                "potential": 100 - self.hierarchy_score,
            },
            "motion": {
                "score": self.motion_score,
                "weight": 0.25,
                "potential": 100 - self.motion_score,
            },
        }

    def get_100_recommendations(self) -> list[dict]:
        """Get prioritized recommendations to reach 100/100."""
        recs = []

        # Sort by impact (issues that cost the most points)
        errors = self.get_errors()
        warnings = self.get_warnings()

        for issue in errors:
            recs.append(
                {
                    "priority": "CRITICAL",
                    "category": issue.category,
                    "issue": issue.message,
                    "fix": issue.fix_description if issue.fix_available else "Manual fix required",
                    "impact": "-20 points",
                    "auto_fixable": issue.fix_available,
                }
            )

        for issue in warnings:
            recs.append(
                {
                    "priority": "HIGH",
                    "category": issue.category,
                    "issue": issue.message,
                    "fix": issue.fix_description if issue.fix_available else "Review and adjust",
                    "impact": "-10 points",
                    "auto_fixable": issue.fix_available,
                }
            )

        # Add score-specific recommendations
        breakdown = self.get_score_breakdown()
        lowest_score = min(breakdown.items(), key=lambda x: x[1]["score"])

        if lowest_score[1]["score"] < 80:
            recs.append(
                {
                    "priority": "HIGH",
                    "category": lowest_score[0],
                    "issue": f"Lowest score: {lowest_score[1]['score']:.1f}/100",
                    "fix": f"Focus on improving {lowest_score[0]} quality",
                    "impact": f"+{lowest_score[1]['potential']:.0f} points potential",
                    "auto_fixable": False,
                }
            )

        # Sort by priority
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        recs.sort(key=lambda x: priority_order.get(x["priority"], 4))

        return recs

    def print_report(self):
        """Print formatted report to console."""
        print("=" * 70)
        print("DESIGN QUALITY REPORT")
        print("=" * 70)
        print("\n📊 SCORES:")
        print(f"   Overall:    {self.overall_score:.1f}/100")
        print(f"   Technical:  {self.technical_score:.1f}/100")
        print(f"   Design:     {self.design_score:.1f}/100")
        print(f"   Hierarchy:  {self.hierarchy_score:.1f}/100")
        print(f"   Motion:     {self.motion_score:.1f}/100")

        print("\n📋 ISSUES:")
        print(f"   Errors:   {len(self.get_errors())}")
        print(f"   Warnings: {len(self.get_warnings())}")
        print(f"   Info:     {len(self.issues) - len(self.get_errors()) - len(self.get_warnings())}")

        if self.recommendations:
            print("\n🎯 RECOMMENDATIONS TO REACH 100/100:")
            for i, rec in enumerate(self.recommendations[:10], 1):
                icon = "🔴" if rec["priority"] == "CRITICAL" else "🟡" if rec["priority"] == "HIGH" else "🔵"
                auto = " [AUTO]" if rec.get("auto_fixable") else ""
                print(f"   {icon} {i}. [{rec['category'].upper()}] {rec['issue']}{auto}")
                print(f"      Fix: {rec['fix']}")
                print(f"      Impact: {rec['impact']}")

        if self.fixes_applied:
            print("\n✅ FIXES APPLIED:")
            for fix in self.fixes_applied:
                print(f"   ✓ {fix}")

        print(f"\n{'=' * 70}")
