#!/usr/bin/env python3
"""
Run the data pipeline CLI.

Usage:
    python -m data_pipeline <command> [options]

Commands:
    status    - Show current data status
    sources   - List available data sources
    fetch     - Fetch data from sources
    import    - Import data from files
    process   - Process existing data
    run       - Run full pipeline
    validate  - Validate data files

Examples:
    python -m data_pipeline status
    python -m data_pipeline fetch --all
    python -m data_pipeline fetch --source gdelt --process
    python -m data_pipeline import data.csv --tier 3
    python -m data_pipeline process
    python -m data_pipeline run --force
"""

from .cli import main

if __name__ == '__main__':
    main()
