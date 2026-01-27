# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Data analysis project documenting violent confrontations between ICE/CBP agents and non-immigrants (protesters, journalists, bystanders, US citizens, officers) during immigration enforcement operations from January 2025 to January 2026. The analysis correlates incident geographic concentration with sanctuary jurisdiction policies.

## Common Commands

```bash
# Setup (first time)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Activate venv (subsequent sessions)
source .venv/bin/activate

# Generate visualizations
python scripts/generate_county_map.py           # Full incident map
python scripts/generate_county_map_filtered.py  # Counties with 4+ incidents only
python scripts/generate_pie_charts.py           # Statistical breakdown charts

# Run analysis (outputs CSVs to output/)
python scripts/run_analysis.py

# Validate data integrity
python scripts/validate_schema.py
```

```bash
# Run web app
streamlit run app/app.py
```

**Output locations:**
- Visualizations: project root (`*.png`)
- Analysis CSVs: `output/` directory

## Architecture

### Data Pipeline

The project uses a tiered confidence system for incident data:

| Tier | Source Type | Confidence | Used in Ratios |
|------|-------------|------------|----------------|
| 1 | Official government (ICE, DOJ, FOIA) | HIGH | Yes |
| 2 | Investigative journalism (ProPublica, The Trace) | MEDIUM-HIGH | Yes |
| 3 | Systematic news search (AP, Reuters, major outlets) | MEDIUM | No |
| 4 | Ad-hoc reports (local news, verified social media) | LOW | No |

### Data Flow

1. **Ingestion** (`scripts/extract_data_to_json.py`) - Converts source data to JSON
2. **Augmentation** (`scripts/add_round*_incidents.py`) - Iterative data additions
3. **Geocoding** (`scripts/expand_city_data.py`) - Maps cities to counties via FIPS codes
4. **Deduplication** (`scripts/populate_canonical_ids.py`, `scripts/link_duplicates.py`)
5. **Validation** (`scripts/validate_schema.py`) - Enforces schema consistency
6. **Visualization** (`scripts/generate_*.py`) - Produces maps and charts

### Key Data Files

- `data/incidents/tier*.json` - Incident records by confidence tier
- `data/reference/sanctuary_jurisdictions.json` - State/city policy classifications with source URLs
- `data/methodology.json` - Complete methodology documentation and source tier definitions

### City-to-County Mapping

The mapping in `scripts/generate_county_map.py:14-225` (`CITY_TO_COUNTY` dict) converts incident city names to FIPS codes for geographic aggregation. When adding new cities, include: `("County Name", "State FIPS", "County FIPS")`.

### Schema Requirements

All incident records must include (enforced by `validate_schema.py`):
- `id`, `date`, `state`, `incident_type`, `source_tier`, `verified`
- `affected_count`, `incident_scale`, `outcome`, `outcome_detail`, `outcome_category`
- `victim_category`, `date_precision`

Valid `victim_category` values: `detainee`, `enforcement_target`, `protester`, `journalist`, `bystander`, `us_citizen_collateral`, `officer`, `multiple`

Valid `incident_scale` values: `single` (1), `small` (2-5), `medium` (6-50), `large` (51-200), `mass` (200+)

## Web App Architecture

The `app/` directory contains an interactive dashboard:

- `app/data.py` - Data loading/processing layer (framework-agnostic, reusable)
- `app/app.py` - Streamlit UI (can be swapped for FastAPI+React later)

The data layer is intentionally separated so the backend logic can be reused with a different frontend without rewriting.

## Non-Immigrant Filtering Logic

The analysis focuses on non-enforcement targets. An incident is classified as "non-immigrant" if:
```python
victim_category in ['us_citizen', 'bystander', 'officer', 'protester', 'journalist'] or
us_citizen == True or
protest_related == True
```
