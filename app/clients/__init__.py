"""
FHIR and external service clients
"""

from .fhir_client import FHIRClient, create_fhir_client

__all__ = ['FHIRClient', 'create_fhir_client']
