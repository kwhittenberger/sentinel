#!/usr/bin/env python3
"""
Command-line interface for the ICE Incidents Data Pipeline.

Usage:
    python -m data_pipeline.cli fetch --all           # Fetch from all sources
    python -m data_pipeline.cli fetch --source ice_deaths  # Fetch from specific source
    python -m data_pipeline.cli import data.csv --tier 3   # Import CSV file
    python -m data_pipeline.cli process                     # Process all data
    python -m data_pipeline.cli run                         # Full pipeline run
    python -m data_pipeline.cli status                      # Show current data status
"""

import argparse
import sys
import json
import logging
from pathlib import Path
from typing import Optional

from .pipeline import DataPipeline, run_pipeline
from .config import SOURCES, INCIDENTS_DIR, DATA_DIR


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_fetch(args):
    """Fetch data from sources."""
    pipeline = DataPipeline()

    if args.all:
        print("Fetching from all enabled sources...")
        count = pipeline.fetch_all(force_refresh=args.force)
        print(f"Fetched {count} total incidents")
    elif args.source:
        if args.source not in SOURCES:
            print(f"Unknown source: {args.source}")
            print(f"Available sources: {', '.join(SOURCES.keys())}")
            return 1
        print(f"Fetching from {args.source}...")
        count = pipeline.fetch_source(args.source, force_refresh=args.force)
        print(f"Fetched {count} incidents")
    else:
        print("Specify --all or --source <name>")
        return 1

    # Optionally process and save
    if args.process:
        print("\nProcessing incidents...")
        stats = pipeline.process()
        print(f"Processed: {stats['total']} total incidents")

        print("\nSaving to files...")
        files = pipeline.save()
        for f in files:
            print(f"  - {f.name}")

    return 0


def cmd_import(args):
    """Import data from files."""
    pipeline = DataPipeline()

    for filepath in args.files:
        path = Path(filepath)
        if not path.exists():
            print(f"File not found: {filepath}")
            continue

        if path.suffix.lower() == '.csv':
            count = pipeline.import_csv(str(path), tier=args.tier)
            print(f"Imported {count} incidents from {path.name}")
        elif path.suffix.lower() == '.json':
            count = pipeline.import_json(str(path), tier=args.tier)
            print(f"Imported {count} incidents from {path.name}")
        else:
            print(f"Unsupported file type: {path.suffix}")

    # Process and save
    if args.process:
        print("\nProcessing imported data...")
        stats = pipeline.process()
        print(f"Processed: {stats['total']} total incidents")

        print("\nSaving to files...")
        files = pipeline.save()
        for f in files:
            print(f"  - {f.name}")

    return 0


def cmd_process(args):
    """Process existing data."""
    pipeline = DataPipeline()

    # Load existing data
    print("Loading existing data...")
    existing_files = list(INCIDENTS_DIR.glob("*.json"))

    for filepath in existing_files:
        # Skip metadata files
        if 'metadata' in filepath.name or not filepath.stem.startswith('tier'):
            continue
        try:
            tier = int(filepath.stem.split('_')[0].replace('tier', ''))
            pipeline.import_json(str(filepath), tier=tier)
            print(f"  Loaded {filepath.name}")
        except Exception as e:
            print(f"  Failed to load {filepath.name}: {e}")

    # Process
    print("\nProcessing...")
    stats = pipeline.process(
        validate=not args.skip_validation,
        normalize=not args.skip_normalize,
        deduplicate=not args.skip_dedupe,
        geocode=not args.skip_geocode,
    )

    print(f"\nProcessing Results:")
    print(f"  Original counts: {stats['original_counts']}")
    print(f"  Final counts: {stats['final_counts']}")
    print(f"  Validation errors: {stats['validation_errors']}")
    print(f"  Duplicates removed: {stats['duplicates_removed']}")
    print(f"  Newly geocoded: {stats['geocoded']}")
    print(f"  Total incidents: {stats['total']}")

    # Save
    if not args.dry_run:
        print("\nSaving...")
        files = pipeline.save(merge_existing=False)
        for f in files:
            print(f"  - {f.name}")

    return 0


def cmd_run(args):
    """Run full pipeline."""
    print("Running full data pipeline...")
    print("=" * 50)

    sources = args.sources.split(',') if args.sources else None
    import_files = args.import_files.split(',') if args.import_files else None

    results = run_pipeline(
        sources=sources,
        import_files=import_files,
        force_refresh=args.force,
        output_dir=args.output_dir,
    )

    print("\n" + "=" * 50)
    print("Pipeline Complete!")
    print("=" * 50)

    stats = results['processing_stats']
    summary = results['summary']

    print(f"\nProcessing Stats:")
    print(f"  Validation errors: {stats['validation_errors']}")
    print(f"  Duplicates removed: {stats['duplicates_removed']}")
    print(f"  Newly geocoded: {stats['geocoded']}")

    print(f"\nData Summary:")
    print(f"  Total incidents: {summary['total_incidents']}")
    print(f"  By tier: {summary['by_tier']}")
    print(f"  Deaths: {summary['deaths']}")
    print(f"  With coordinates: {summary['with_coordinates']}")

    if summary['by_state']:
        print(f"\n  Top states:")
        sorted_states = sorted(summary['by_state'].items(), key=lambda x: -x[1])[:5]
        for state, count in sorted_states:
            print(f"    {state}: {count}")

    return 0


def cmd_status(args):
    """Show current data status."""
    print("ICE Incidents Data Pipeline Status")
    print("=" * 50)

    # Check data directory
    print(f"\nData Directory: {DATA_DIR}")
    print(f"Incidents Directory: {INCIDENTS_DIR}")

    if not INCIDENTS_DIR.exists():
        print("\n  No incident data found.")
        return 0

    # List existing files
    print(f"\nExisting data files:")
    total_incidents = 0

    for filepath in sorted(INCIDENTS_DIR.glob("*.json")):
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else 0
            total_incidents += count
            print(f"  {filepath.name}: {count} incidents")
        except Exception as e:
            print(f"  {filepath.name}: Error reading ({e})")

    print(f"\nTotal: {total_incidents} incidents")

    # Check sources
    print(f"\nConfigured Sources:")
    for name, config in SOURCES.items():
        status = "enabled" if config.enabled else "disabled"
        api_note = " (requires API key)" if config.requires_api_key else ""
        print(f"  {name}: Tier {config.tier}, {status}{api_note}")

    # Check cache
    cache_dir = DATA_DIR / ".cache"
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*.json"))
        print(f"\nCache: {len(cache_files)} cached responses")

    return 0


def cmd_sources(args):
    """List available sources."""
    print("Available Data Sources")
    print("=" * 50)

    for tier in [1, 2, 3, 4]:
        tier_sources = [
            (name, config) for name, config in SOURCES.items()
            if config.tier == tier
        ]

        if tier_sources:
            print(f"\nTier {tier}:")
            for name, config in tier_sources:
                status = "[enabled]" if config.enabled else "[disabled]"
                api_note = " (API key required)" if config.requires_api_key else ""
                print(f"  {name}: {config.name} {status}{api_note}")
                print(f"    URL: {config.url}")

    return 0


def cmd_validate(args):
    """Validate a data file."""
    from .importers.validator import SchemaValidator
    from .sources.base import Incident

    validator = SchemaValidator()

    for filepath in args.files:
        path = Path(filepath)
        if not path.exists():
            print(f"File not found: {filepath}")
            continue

        print(f"\nValidating {path.name}...")

        try:
            with open(path, 'r') as f:
                data = json.load(f)

            if not isinstance(data, list):
                print("  Error: Expected a JSON array")
                continue

            incidents = [Incident.from_dict(d) for d in data]
            valid, results = validator.validate_batch(incidents)

            errors = sum(len(r.errors) for r in results)
            warnings = sum(len(r.warnings) for r in results)

            print(f"  Total records: {len(incidents)}")
            print(f"  Valid records: {len(valid)}")
            print(f"  Errors: {errors}")
            print(f"  Warnings: {warnings}")

            if args.verbose and errors > 0:
                print(f"\n  Sample errors:")
                for r in results[:5]:
                    if r.errors:
                        print(f"    Record {r.incident_id}:")
                        for err in r.errors[:3]:
                            print(f"      - {err}")

        except Exception as e:
            print(f"  Error: {e}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="ICE Incidents Data Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('-v', '--verbose', action='store_true', help="Verbose output")

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # fetch command
    fetch_parser = subparsers.add_parser('fetch', help='Fetch data from sources')
    fetch_parser.add_argument('--all', action='store_true', help='Fetch from all enabled sources')
    fetch_parser.add_argument('--source', type=str, help='Specific source to fetch')
    fetch_parser.add_argument('--force', action='store_true', help='Force refresh (ignore cache)')
    fetch_parser.add_argument('--process', action='store_true', help='Process and save after fetching')

    # import command
    import_parser = subparsers.add_parser('import', help='Import data from files')
    import_parser.add_argument('files', nargs='+', help='Files to import (CSV or JSON)')
    import_parser.add_argument('--tier', type=int, default=4, help='Data tier (1-4)')
    import_parser.add_argument('--process', action='store_true', help='Process and save after importing')

    # process command
    process_parser = subparsers.add_parser('process', help='Process existing data')
    process_parser.add_argument('--dry-run', action='store_true', help='Do not save results')
    process_parser.add_argument('--skip-validation', action='store_true', help='Skip validation')
    process_parser.add_argument('--skip-normalize', action='store_true', help='Skip normalization')
    process_parser.add_argument('--skip-dedupe', action='store_true', help='Skip deduplication')
    process_parser.add_argument('--skip-geocode', action='store_true', help='Skip geocoding')

    # run command
    run_parser = subparsers.add_parser('run', help='Run full pipeline')
    run_parser.add_argument('--sources', type=str, help='Comma-separated list of sources')
    run_parser.add_argument('--import-files', type=str, help='Comma-separated list of files to import')
    run_parser.add_argument('--force', action='store_true', help='Force refresh')
    run_parser.add_argument('--output-dir', type=str, help='Override output directory')

    # status command
    subparsers.add_parser('status', help='Show current data status')

    # sources command
    subparsers.add_parser('sources', help='List available sources')

    # validate command
    validate_parser = subparsers.add_parser('validate', help='Validate data files')
    validate_parser.add_argument('files', nargs='+', help='Files to validate')
    validate_parser.add_argument('--verbose', action='store_true', help='Show detailed errors')

    args = parser.parse_args()

    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        'fetch': cmd_fetch,
        'import': cmd_import,
        'process': cmd_process,
        'run': cmd_run,
        'status': cmd_status,
        'sources': cmd_sources,
        'validate': cmd_validate,
    }

    return commands[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
