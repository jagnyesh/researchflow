"""
Statistics Calculator

Computes summary statistics for query results
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SummaryStats:
    """Summary statistics for a dataset"""
    total_count: int
    gender_distribution: Dict[str, int]
    age_stats: Optional[Dict[str, float]]
    condition_prevalence: Optional[Dict[str, int]]
    date_range: Optional[Dict[str, str]]
    top_values: Dict[str, List[tuple]]  # Top values for categorical fields


class StatsCalculator:
    """
    Calculate summary statistics for query results

    Provides methods for computing:
    - Counts and distributions
    - Age statistics (min, max, mean, median)
    - Gender distribution
    - Condition prevalence
    - Date ranges
    """

    @staticmethod
    def calculate_stats(rows: List[Dict[str, Any]], resource_type: str = "Patient") -> SummaryStats:
        """
        Calculate comprehensive statistics for result set

        Args:
            rows: Query result rows
            resource_type: Type of FHIR resource

        Returns:
            SummaryStats object
        """
        if not rows:
            return SummaryStats(
                total_count=0,
                gender_distribution={},
                age_stats=None,
                condition_prevalence=None,
                date_range=None,
                top_values={}
            )

        total_count = len(rows)

        # Gender distribution
        gender_dist = StatsCalculator._calculate_gender_distribution(rows)

        # Age statistics
        age_stats = StatsCalculator._calculate_age_stats(rows)

        # Condition prevalence (if condition data present)
        condition_prevalence = StatsCalculator._calculate_condition_prevalence(rows)

        # Date range
        date_range = StatsCalculator._calculate_date_range(rows)

        # Top values for key fields
        top_values = StatsCalculator._calculate_top_values(rows)

        return SummaryStats(
            total_count=total_count,
            gender_distribution=gender_dist,
            age_stats=age_stats,
            condition_prevalence=condition_prevalence,
            date_range=date_range,
            top_values=top_values
        )

    @staticmethod
    def _calculate_gender_distribution(rows: List[Dict]) -> Dict[str, int]:
        """Calculate gender distribution"""
        genders = [row.get("gender") for row in rows if row.get("gender")]
        if not genders:
            return {}

        gender_counts = Counter(genders)
        return dict(gender_counts)

    @staticmethod
    def _calculate_age_stats(rows: List[Dict]) -> Optional[Dict[str, float]]:
        """Calculate age statistics from birth dates"""
        birth_dates = []
        current_year = datetime.now().year

        for row in rows:
            birth_date_str = row.get("birth_date")
            if birth_date_str:
                try:
                    if isinstance(birth_date_str, str):
                        birth_year = int(birth_date_str[:4])
                        age = current_year - birth_year
                        if 0 <= age <= 150:  # Sanity check
                            birth_dates.append(age)
                except (ValueError, IndexError):
                    continue

        if not birth_dates:
            return None

        # Calculate statistics
        ages_sorted = sorted(birth_dates)
        n = len(ages_sorted)

        stats = {
            "min": ages_sorted[0],
            "max": ages_sorted[-1],
            "mean": sum(ages_sorted) / n,
            "median": ages_sorted[n // 2] if n % 2 == 1 else (ages_sorted[n // 2 - 1] + ages_sorted[n // 2]) / 2,
            "count": n
        }

        return stats

    @staticmethod
    def _calculate_condition_prevalence(rows: List[Dict]) -> Optional[Dict[str, int]]:
        """Calculate condition prevalence if condition data present"""
        conditions = []

        for row in rows:
            # Try different condition field names
            condition_name = (
                row.get("snomed_display") or
                row.get("icd10_display") or
                row.get("code_text") or
                row.get("condition_name")
            )

            if condition_name:
                conditions.append(condition_name)

        if not conditions:
            return None

        condition_counts = Counter(conditions)
        # Return top 10 conditions
        return dict(condition_counts.most_common(10))

    @staticmethod
    def _calculate_date_range(rows: List[Dict]) -> Optional[Dict[str, str]]:
        """Calculate date range from various date fields"""
        dates = []

        date_fields = [
            "birth_date", "onset_datetime", "recorded_date",
            "effective_datetime", "performed_datetime", "authored_on"
        ]

        for row in rows:
            for field in date_fields:
                date_str = row.get(field)
                if date_str:
                    try:
                        # Extract just the date part (YYYY-MM-DD)
                        date_part = date_str[:10]
                        dates.append(date_part)
                    except (IndexError, TypeError):
                        continue

        if not dates:
            return None

        dates_sorted = sorted(dates)
        return {
            "earliest": dates_sorted[0],
            "latest": dates_sorted[-1],
            "span_days": (
                datetime.fromisoformat(dates_sorted[-1]) -
                datetime.fromisoformat(dates_sorted[0])
            ).days
        }

    @staticmethod
    def _calculate_top_values(rows: List[Dict], max_per_field: int = 5) -> Dict[str, List[tuple]]:
        """Calculate top values for categorical fields"""
        # Fields to analyze
        categorical_fields = [
            "gender", "state", "city", "clinical_status",
            "verification_status", "category", "status"
        ]

        top_values = {}

        for field in categorical_fields:
            values = [row.get(field) for row in rows if row.get(field)]
            if values:
                value_counts = Counter(values)
                top_values[field] = value_counts.most_common(max_per_field)

        return top_values

    @staticmethod
    def format_stats_for_display(stats: SummaryStats) -> str:
        """
        Format statistics for human-readable display

        Returns:
            Formatted string with statistics
        """
        lines = []

        # Total count
        lines.append(f"**Total:** {stats.total_count:,} records")

        # Gender distribution
        if stats.gender_distribution:
            gender_strs = [
                f"{gender.capitalize()}: {count} ({count/stats.total_count*100:.1f}%)"
                for gender, count in stats.gender_distribution.items()
            ]
            lines.append(f"**Gender:** {', '.join(gender_strs)}")

        # Age statistics
        if stats.age_stats:
            age_info = stats.age_stats
            lines.append(
                f"**Age:** {age_info['min']:.0f}-{age_info['max']:.0f} years "
                f"(mean: {age_info['mean']:.1f}, median: {age_info['median']:.1f})"
            )

        # Condition prevalence
        if stats.condition_prevalence:
            top_conditions = list(stats.condition_prevalence.items())[:3]
            cond_strs = [f"{name} ({count})" for name, count in top_conditions]
            lines.append(f"**Top Conditions:** {', '.join(cond_strs)}")

        # Date range
        if stats.date_range:
            date_info = stats.date_range
            lines.append(
                f"**Date Range:** {date_info['earliest']} to {date_info['latest']} "
                f"({date_info['span_days']} days)"
            )

        return "\n\n".join(lines)
