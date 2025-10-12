"""
Terminology MCP Server

Provides access to medical terminology systems (SNOMED, LOINC, RxNorm).
"""

import logging
from .mcp_registry import BaseMCPServer

logger = logging.getLogger(__name__)


class TerminologyMCPServer(BaseMCPServer):
    """
    MCP server for medical terminology lookups

    Tools:
    - search_snomed: Search SNOMED-CT codes
    - search_loinc: Search LOINC codes
    - search_rxnorm: Search RxNorm medication codes
    """

    def __init__(self):
        super().__init__(server_id="terminology_server")
        self._register_tools()

    def _register_tools(self):
        """Register available tools"""
        self.register_tool("search_snomed", self._search_snomed)
        self.register_tool("search_loinc", self._search_loinc)
        self.register_tool("search_rxnorm", self._search_rxnorm)

    async def _search_snomed(self, parameters: dict) -> dict:
        """
        Search SNOMED-CT codes

        Parameters:
            search_term: Text to search for

        Returns:
            Dict with results list
        """
        search_term = parameters.get('search_term', '')
        logger.debug(f"[{self.server_id}] Searching SNOMED for: {search_term}")

        # TODO: Implement actual SNOMED API integration
        # For now, return mock results
        mock_results = self._get_mock_snomed_codes(search_term)

        return {
            "results": mock_results,
            "total": len(mock_results)
        }

    async def _search_loinc(self, parameters: dict) -> dict:
        """
        Search LOINC codes

        Parameters:
            search_term: Text to search for

        Returns:
            Dict with results list
        """
        search_term = parameters.get('search_term', '')
        logger.debug(f"[{self.server_id}] Searching LOINC for: {search_term}")

        # TODO: Implement actual LOINC API integration
        mock_results = self._get_mock_loinc_codes(search_term)

        return {
            "results": mock_results,
            "total": len(mock_results)
        }

    async def _search_rxnorm(self, parameters: dict) -> dict:
        """
        Search RxNorm medication codes

        Parameters:
            search_term: Text to search for

        Returns:
            Dict with results list
        """
        search_term = parameters.get('search_term', '')
        logger.debug(f"[{self.server_id}] Searching RxNorm for: {search_term}")

        # TODO: Implement actual RxNorm API integration
        mock_results = self._get_mock_rxnorm_codes(search_term)

        return {
            "results": mock_results,
            "total": len(mock_results)
        }

    def _get_mock_snomed_codes(self, search_term: str) -> list:
        """Get mock SNOMED codes for testing"""
        # Common medical conditions
        mock_data = {
            "diabetes": [
                {"code": "73211009", "display": "Diabetes mellitus", "system": "SNOMED-CT"},
                {"code": "44054006", "display": "Type 2 diabetes mellitus", "system": "SNOMED-CT"}
            ],
            "heart failure": [
                {"code": "84114007", "display": "Heart failure", "system": "SNOMED-CT"},
                {"code": "42343007", "display": "Congestive heart failure", "system": "SNOMED-CT"}
            ],
            "hypertension": [
                {"code": "38341003", "display": "Hypertensive disorder", "system": "SNOMED-CT"}
            ]
        }

        search_lower = search_term.lower()
        for key, codes in mock_data.items():
            if key in search_lower:
                return codes

        return []

    def _get_mock_loinc_codes(self, search_term: str) -> list:
        """Get mock LOINC codes for testing"""
        mock_data = {
            "hemoglobin": [
                {"code": "718-7", "display": "Hemoglobin [Mass/volume] in Blood", "system": "LOINC"}
            ],
            "glucose": [
                {"code": "2345-7", "display": "Glucose [Mass/volume] in Serum or Plasma", "system": "LOINC"}
            ],
            "creatinine": [
                {"code": "2160-0", "display": "Creatinine [Mass/volume] in Serum or Plasma", "system": "LOINC"}
            ]
        }

        search_lower = search_term.lower()
        for key, codes in mock_data.items():
            if key in search_lower:
                return codes

        return []

    def _get_mock_rxnorm_codes(self, search_term: str) -> list:
        """Get mock RxNorm codes for testing"""
        mock_data = {
            "metformin": [
                {"code": "6809", "display": "Metformin", "system": "RxNorm"}
            ],
            "insulin": [
                {"code": "5856", "display": "Insulin", "system": "RxNorm"}
            ],
            "lisinopril": [
                {"code": "29046", "display": "Lisinopril", "system": "RxNorm"}
            ]
        }

        search_lower = search_term.lower()
        for key, codes in mock_data.items():
            if key in search_lower:
                return codes

        return []
