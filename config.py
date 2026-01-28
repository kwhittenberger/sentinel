"""Project configuration."""

from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).parent

# Output directory for generated files
OUTPUT_DIR = PROJECT_ROOT / "output"

# Data directory
DATA_DIR = PROJECT_ROOT / "data"

# Incidents directory
INCIDENTS_DIR = DATA_DIR / "incidents"
