"""
Centralized confidence thresholds -- single source of truth.

All threshold values used across the pipeline (auto-approval, duplicate
detection, curation routing) are defined here.  Individual services and
pipeline stages import these constants instead of hard-coding magic numbers.

The values serve as defaults; the settings service and database-backed
incident-type configs can override them at runtime.
"""

# ---------------------------------------------------------------------------
# Auto-approval confidence thresholds
# ---------------------------------------------------------------------------

# Overall extraction confidence required for auto-approval (standard)
AUTO_APPROVE_CONFIDENCE = 0.85

# Enforcement category uses higher scrutiny
ENFORCEMENT_AUTO_APPROVE_CONFIDENCE = 0.90

# Crime category threshold (same as standard, explicit for clarity)
CRIME_AUTO_APPROVE_CONFIDENCE = 0.85

# Domain categories (Criminal Justice, Civil Rights, etc.)
DOMAIN_AUTO_APPROVE_CONFIDENCE = 0.85

# Minimum confidence for human review (below this = full manual review)
REVIEW_CONFIDENCE = 0.50

# Below this confidence, auto-reject the article
AUTO_REJECT_CONFIDENCE = 0.30

# Per-field confidence: required confidence for individual extracted fields
FIELD_CONFIDENCE_THRESHOLD = 0.70

# Enforcement fields need slightly higher per-field confidence
ENFORCEMENT_FIELD_CONFIDENCE_THRESHOLD = 0.75

# ---------------------------------------------------------------------------
# Duplicate detection similarity thresholds
# ---------------------------------------------------------------------------

# Jaccard similarity between article titles to flag as duplicate
DUPLICATE_TITLE_SIMILARITY = 0.75

# Min-hash fingerprint similarity between article content
DUPLICATE_CONTENT_SIMILARITY = 0.85

# Content dedup pipeline stage uses a slightly lower content threshold
CONTENT_DEDUPE_TITLE_THRESHOLD = 0.85
CONTENT_DEDUPE_CONTENT_THRESHOLD = 0.80

# Fuzzy name matching threshold for entity-based dedup
DUPLICATE_NAME_SIMILARITY = 0.70

# Date window (days) for entity-based duplicate matching
DUPLICATE_ENTITY_DATE_WINDOW = 30

# ---------------------------------------------------------------------------
# Severity thresholds (crime seriousness gates for auto-approval)
# ---------------------------------------------------------------------------

# Minimum severity score for auto-approval of standard incidents
MIN_SEVERITY_AUTO_APPROVE = 5

# Below this severity, auto-reject the incident
MAX_SEVERITY_AUTO_REJECT = 2

# Enforcement incidents use lower severity gate (raids, arrests aren't "crimes")
ENFORCEMENT_MIN_SEVERITY_AUTO_APPROVE = 1

# Domain categories effectively disable severity gating
DOMAIN_MIN_SEVERITY_AUTO_APPROVE = 0
DOMAIN_MAX_SEVERITY_AUTO_REJECT = 0

# ---------------------------------------------------------------------------
# Source reliability
# ---------------------------------------------------------------------------

MIN_SOURCE_RELIABILITY = 0.60
