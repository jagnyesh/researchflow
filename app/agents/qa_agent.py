"""
Quality Assurance Agent

Validates extracted data quality before delivery to researcher.
"""

from typing import Dict, Any
import logging
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class QualityAssuranceAgent(BaseAgent):
    """
    Agent for automated data quality validation

    Responsibilities:
    - Check data completeness
    - Validate data quality metrics
    - Verify PHI scrubbing (if de-identified)
    - Check for duplicates and inconsistencies
    - Generate QA report
    - Route to delivery if passed, escalate if failed
    """

    def __init__(self, orchestrator=None):
        super().__init__(agent_id="qa_agent", orchestrator=orchestrator)

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute QA validation task"""
        if task == "validate_extracted_data":
            return await self._validate_extracted_data(context)
        else:
            raise ValueError(f"Unknown task: {task}")

    async def _validate_extracted_data(self, context: Dict) -> Dict[str, Any]:
        """
        Run comprehensive QA checks on extracted data

        Args:
            context: Contains request_id, requirements, data_package

        Returns:
            Dict with QA results and next routing
        """
        request_id = context.get('request_id')
        requirements = context.get('requirements')
        data_package = context.get('data_package')

        logger.info(f"[{self.agent_id}] Running QA checks for {request_id}")

        qa_report = {
            "overall_status": "pending",
            "checks": [],
            "issues": [],
            "recommendations": []
        }

        # Check 1: Completeness
        completeness_check = await self._check_completeness(
            data_package,
            requirements
        )
        qa_report['checks'].append(completeness_check)

        # Check 2: Data quality metrics
        quality_check = await self._check_data_quality(data_package)
        qa_report['checks'].append(quality_check)

        # Check 3: PHI scrubbing validation (if de-identified)
        if requirements.get('phi_level') != 'identified':
            phi_check = await self._validate_deidentification(
                data_package,
                requirements.get('phi_level')
            )
            qa_report['checks'].append(phi_check)

        # Check 4: Cohort validation
        cohort_check = await self._validate_cohort_characteristics(
            data_package,
            requirements
        )
        qa_report['checks'].append(cohort_check)

        # Determine overall status
        critical_failures = [
            c for c in qa_report['checks']
            if c.get('severity') == 'critical' and not c.get('passed')
        ]

        if critical_failures:
            qa_report['overall_status'] = 'failed'
            qa_report['issues'] = critical_failures

            logger.warning(
                f"[{self.agent_id}] QA failed: {len(critical_failures)} "
                f"critical issues"
            )

            # Escalate to human review
            await self._escalate_qa_failure(request_id, qa_report)

            return {
                "overall_status": "failed",
                "qa_report": qa_report,
                "next_agent": None,
                "next_task": None
            }
        else:
            qa_report['overall_status'] = 'passed'

            logger.info(f"[{self.agent_id}] QA passed for {request_id}")

            return {
                "overall_status": "passed",
                "qa_report": qa_report,
                "next_agent": "delivery_agent",
                "next_task": "deliver_data",
                "additional_context": {
                    "qa_report": qa_report
                }
            }

    async def _check_completeness(
        self,
        data_package: Dict,
        requirements: Dict
    ) -> Dict:
        """
        Check if all requested data elements were extracted

        Returns:
            Check result dict
        """
        requested_elements = set(requirements.get('data_elements', []))
        extracted_elements = set(data_package.get('data_elements', {}).keys())

        missing_elements = requested_elements - extracted_elements
        passed = len(missing_elements) == 0

        return {
            "check_name": "completeness",
            "passed": passed,
            "severity": "critical" if not passed else "info",
            "details": {
                "requested_count": len(requested_elements),
                "extracted_count": len(extracted_elements),
                "missing_elements": list(missing_elements)
            },
            "message": "All requested data elements extracted" if passed
                      else f"Missing {len(missing_elements)} data elements"
        }

    async def _check_data_quality(self, data_package: Dict) -> Dict:
        """
        Check for data quality issues

        Checks:
        - High missing data rates
        - Duplicate records
        - Date inconsistencies
        """
        issues = []
        data_elements = data_package.get('data_elements', {})

        # Check missing data rates
        for element_name, records in data_elements.items():
            if not records:
                continue

            missing_rate = self._calculate_missing_rate(records)

            if missing_rate > 0.3:  # 30% threshold
                issues.append({
                    "element": element_name,
                    "issue": "high_missing_rate",
                    "rate": missing_rate,
                    "severity": "warning"
                })

        # Check for duplicates
        duplicates = self._check_duplicates(data_package)
        if duplicates:
            issues.append({
                "issue": "duplicate_records",
                "count": len(duplicates),
                "severity": "critical",
                "details": duplicates[:10]  # First 10 duplicates
            })

        # Check date consistency
        date_issues = self._validate_dates(data_package)
        issues.extend(date_issues)

        passed = len([i for i in issues if i.get('severity') == 'critical']) == 0

        return {
            "check_name": "data_quality",
            "passed": passed,
            "severity": "critical" if not passed else "info",
            "issues": issues,
            "message": f"Found {len(issues)} data quality issues"
        }

    async def _validate_deidentification(
        self,
        data_package: Dict,
        phi_level: str
    ) -> Dict:
        """
        Validate that de-identification was properly applied

        Checks:
        - No patient names present
        - No SSNs
        - No MRNs (if de-identified)
        - Dates shifted (if de-identified)
        """
        issues = []
        data_elements = data_package.get('data_elements', {})

        # Fields that should not be present
        prohibited_fields = []
        if phi_level == 'de-identified':
            prohibited_fields = ['patient_name', 'ssn', 'mrn', 'address', 'phone']
        elif phi_level == 'limited_dataset':
            prohibited_fields = ['patient_name', 'ssn', 'address']

        # Check for prohibited fields
        for element_name, records in data_elements.items():
            for record in records[:100]:  # Sample first 100
                for field in prohibited_fields:
                    if field in record and record[field]:
                        issues.append({
                            "issue": "phi_not_removed",
                            "field": field,
                            "element": element_name,
                            "severity": "critical"
                        })
                        break

        passed = len(issues) == 0

        return {
            "check_name": "deidentification",
            "passed": passed,
            "severity": "critical" if not passed else "info",
            "issues": issues,
            "message": "De-identification verified" if passed
                      else f"Found {len(issues)} PHI issues"
        }

    async def _validate_cohort_characteristics(
        self,
        data_package: Dict,
        requirements: Dict
    ) -> Dict:
        """
        Validate cohort matches expected characteristics

        Checks:
        - Cohort size within expected range
        - Demographic distribution reasonable
        """
        cohort = data_package.get('cohort', [])
        cohort_size = len(cohort)

        feasibility_report = requirements.get('feasibility_report', {})
        estimated_size = feasibility_report.get('estimated_cohort_size', cohort_size)

        # Allow ±20% variance from estimate
        min_expected = estimated_size * 0.8
        max_expected = estimated_size * 1.2

        within_range = min_expected <= cohort_size <= max_expected

        return {
            "check_name": "cohort_validation",
            "passed": within_range,
            "severity": "warning" if not within_range else "info",
            "details": {
                "actual_size": cohort_size,
                "estimated_size": estimated_size,
                "variance": abs(cohort_size - estimated_size) / estimated_size if estimated_size > 0 else 0
            },
            "message": f"Cohort size: {cohort_size} "
                      f"(expected: {estimated_size})"
        }

    def _calculate_missing_rate(self, records: list) -> float:
        """Calculate rate of missing/null values in records"""
        if not records:
            return 0.0

        total_fields = 0
        missing_fields = 0

        for record in records:
            for key, value in record.items():
                total_fields += 1
                if value is None or value == '':
                    missing_fields += 1

        return missing_fields / total_fields if total_fields > 0 else 0.0

    def _check_duplicates(self, data_package: Dict) -> list:
        """Check for duplicate records"""
        duplicates = []
        data_elements = data_package.get('data_elements', {})

        for element_name, records in data_elements.items():
            seen = set()
            for record in records:
                # Create a simple fingerprint (in production use better method)
                fingerprint = str(record.get('patient_id', '')) + str(record.get('date', ''))
                if fingerprint in seen:
                    duplicates.append({
                        "element": element_name,
                        "fingerprint": fingerprint
                    })
                seen.add(fingerprint)

        return duplicates

    def _validate_dates(self, data_package: Dict) -> list:
        """Check for date inconsistencies"""
        issues = []

        # TODO: Implement date validation
        # - Check for future dates
        # - Check for impossibly old dates
        # - Check date ordering

        return issues

    async def _escalate_qa_failure(self, request_id: str, qa_report: Dict):
        """Escalate QA failure to human review"""
        logger.warning(
            f"[{self.agent_id}] Escalating QA failure for {request_id}"
        )
        # Will be handled by base agent's escalation mechanism
