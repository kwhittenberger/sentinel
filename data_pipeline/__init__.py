"""
ICE Incidents Data Pipeline

A comprehensive data collection system for tracking ICE enforcement incidents.
Supports automated scrapers, manual imports, and API integrations.
"""

from .config import SOURCES, DATA_DIR, INCIDENTS_DIR
from .pipeline import DataPipeline

__version__ = "1.0.0"
__all__ = ["DataPipeline", "SOURCES", "DATA_DIR", "INCIDENTS_DIR"]
