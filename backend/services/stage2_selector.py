"""
Stage 2 Result Selection and Merging.

Replaces naive highest-confidence selection with:
1. Domain-priority-aware selection (Immigration > Criminal Justice > Civil Rights)
2. Entity-clustered multi-schema merging (complementary schemas about the
   same person/event merge into a richer extraction)
3. Cross-contamination prevention (different-entity results stay separate)
"""

import logging
import re
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# Domain priority: higher = preferred when confidence is comparable
DOMAIN_PRIORITY: Dict[str, int] = {
    "immigration": 100,
    "criminal_justice": 50,
    "criminal-justice": 50,
    "civil_rights": 25,
    "civil-rights": 25,
}

DEFAULT_DOMAIN_PRIORITY = 10

# Minimum confidence to consider a stage2 result
MIN_CONFIDENCE_THRESHOLD = 0.3

# Fields that commonly hold the primary person name in extracted data
_PERSON_NAME_FIELDS = [
    "offender_name",
    "person_name",
    "defendant_name",
    "victim_name",
    "suspect_name",
    "individual_name",
    "name",
]


def _normalize_name(name: str) -> str:
    """Lowercase, strip whitespace and punctuation for fuzzy name comparison."""
    if not name:
        return ""
    name = name.strip().lower()
    # Remove common suffixes/prefixes that vary
    name = re.sub(r"[^\w\s]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _extract_entity_name(extracted_data: Dict[str, Any]) -> Optional[str]:
    """Pull the primary person name from extracted_data, checking common field names."""
    if not extracted_data:
        return None
    for field in _PERSON_NAME_FIELDS:
        val = extracted_data.get(field)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _names_match(name_a: str, name_b: str) -> bool:
    """Check if two names refer to the same person (fuzzy)."""
    na = _normalize_name(name_a)
    nb = _normalize_name(name_b)
    if not na or not nb:
        return False
    # Exact normalized match
    if na == nb:
        return True
    # One name is a substring of the other (handles "John Smith" vs "John A. Smith")
    if na in nb or nb in na:
        return True
    # Last-name match: compare last token
    parts_a = na.split()
    parts_b = nb.split()
    if parts_a and parts_b and parts_a[-1] == parts_b[-1] and len(parts_a[-1]) > 2:
        # Same last name — check first initial too if available
        if parts_a[0][0] == parts_b[0][0]:
            return True
    return False


def _get_domain_priority(result: Dict[str, Any]) -> int:
    """Get domain priority for a stage2 result."""
    domain = result.get("domain_slug", "")
    if not domain:
        # Try to infer from schema_name
        schema_name = (result.get("schema_name") or "").lower()
        if "immigration" in schema_name:
            return DOMAIN_PRIORITY["immigration"]
        if "criminal" in schema_name:
            return DOMAIN_PRIORITY["criminal_justice"]
        if "civil" in schema_name:
            return DOMAIN_PRIORITY["civil_rights"]
    return DOMAIN_PRIORITY.get(domain, DEFAULT_DOMAIN_PRIORITY)


def _get_confidence(result: Dict[str, Any]) -> float:
    """Extract confidence as a float from a stage2 result."""
    conf = result.get("confidence")
    if conf is None:
        return 0.0
    try:
        c = float(conf)
        # Normalize: if >1, assume 0-100 scale
        return c / 100.0 if c > 1.0 else c
    except (TypeError, ValueError):
        return 0.0


def resolve_category_from_merge_info(
    merge_info: Optional[Dict[str, Any]],
    extracted_data: Optional[Dict[str, Any]] = None,
    default: str = "crime",
) -> str:
    """
    Resolve the category/slug for an extraction result.

    Priority:
    1. merge_info.sources[0].category_slug (from schema selection)
    2. extracted_data.category (flat field)
    3. extracted_data.categories[] list (enforcement/crime match)
    4. default

    Returns a category string like 'enforcement', 'crime', 'arrest', 'prosecution', etc.
    """
    # 1. Try merge_info sources (most authoritative — comes from schema selection)
    if merge_info:
        sources = merge_info.get("sources")
        if sources and isinstance(sources, list) and len(sources) > 0:
            cat_slug = sources[0].get("category_slug")
            if cat_slug and isinstance(cat_slug, str) and cat_slug.strip():
                return cat_slug.strip()

    if not extracted_data:
        return default

    # 2. Try extracted_data.category (flat field set by some extraction paths)
    cat = extracted_data.get("category")
    if cat and isinstance(cat, str) and cat.strip():
        return cat.strip()

    # 3. Try extracted_data.categories list
    categories = extracted_data.get("categories", [])
    if isinstance(categories, list):
        if "enforcement" in categories:
            return "enforcement"
        if "crime" in categories:
            return "crime"
        # Return first non-empty category if present
        for c in categories:
            if isinstance(c, str) and c.strip():
                return c.strip()

    # 4. Infer from field signature when no explicit category
    #    Articles with CJ fields but no immigration fields are criminal justice
    _cj_signals = ("charges", "court", "case_name", "defendant", "plaintiff",
                   "filing_date", "violation_type", "arresting_agency",
                   "appeal_status", "case_status", "bail_amount", "sentence")
    _enforcement_signals = ("victim_category", "officer_involved",
                           "ice_detainer_ignored", "was_released_sanctuary")
    _immigration_signals = ("offender_immigration_status", "immigration_status",
                           "prior_deportations", "entry_method", "offender_nationality")

    has_cj = any(extracted_data.get(f) for f in _cj_signals)
    has_enforcement = any(extracted_data.get(f) for f in _enforcement_signals)
    has_immigration = any(extracted_data.get(f) for f in _immigration_signals)

    if has_enforcement and has_immigration:
        return "enforcement"
    if has_enforcement:
        return "enforcement"
    if has_immigration:
        return "crime"
    if has_cj:
        # Criminal justice article without immigration data — use 'arrest'
        # which maps to DomainApprovalConfig (requires only date + state)
        return "arrest"

    return default


def select_best_stage2(
    stage2_results: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Pick a single best Stage 2 result using domain priority.

    Drop-in replacement for _pick_best_stage2 that prefers
    Immigration-domain results over higher-confidence CJ results.

    Selection score = domain_priority * confidence.
    """
    if not stage2_results:
        return None

    # Filter below minimum confidence
    candidates = [
        r for r in stage2_results
        if _get_confidence(r) >= MIN_CONFIDENCE_THRESHOLD
    ]
    if not candidates:
        # Fall back to original list if all below threshold
        candidates = stage2_results

    best = None
    best_score = -1.0
    for r in candidates:
        priority = _get_domain_priority(r)
        conf = _get_confidence(r)
        score = priority * conf
        if score > best_score:
            best_score = score
            best = r

    return best


def _cluster_by_entity(
    results: List[Dict[str, Any]],
) -> Dict[Optional[str], List[Dict[str, Any]]]:
    """
    Group stage2 results by primary entity name.

    Results without an extractable entity name go into the None cluster.
    """
    clusters: Dict[Optional[str], List[Dict[str, Any]]] = {}

    for r in results:
        extracted = r.get("extracted_data")
        if isinstance(extracted, str):
            import json
            try:
                extracted = json.loads(extracted)
            except (json.JSONDecodeError, TypeError):
                extracted = {}
        name = _extract_entity_name(extracted or {})

        if name is None:
            clusters.setdefault(None, []).append(r)
            continue

        # Try to match with an existing cluster
        matched_key = None
        for existing_key in clusters:
            if existing_key is not None and _names_match(name, existing_key):
                matched_key = existing_key
                break

        if matched_key is not None:
            clusters[matched_key].append(r)
        else:
            clusters.setdefault(name, []).append(r)

    return clusters


def _pick_primary_cluster(
    clusters: Dict[Optional[str], List[Dict[str, Any]]],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Pick the best cluster:
    1. Prefer clusters containing Immigration-domain results (conf >= 0.5)
    2. Fall back to highest weighted domain_priority * confidence sum
    """
    if not clusters:
        return None, []

    # Score each cluster
    def cluster_score(items: List[Dict[str, Any]]) -> Tuple[bool, float]:
        has_immigration = any(
            _get_domain_priority(r) >= DOMAIN_PRIORITY["immigration"]
            and _get_confidence(r) >= 0.5
            for r in items
        )
        weighted_sum = sum(
            _get_domain_priority(r) * _get_confidence(r)
            for r in items
        )
        return (has_immigration, weighted_sum)

    best_key = None
    best_score = (False, -1.0)
    for key, items in clusters.items():
        score = cluster_score(items)
        if score > best_score:
            best_score = score
            best_key = key

    return best_key, clusters.get(best_key, [])


def _merge_extracted_data(
    cluster: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """
    Merge extracted_data from multiple stage2 results within a cluster.

    Base = highest domain-priority result in the cluster.
    Supplement from other results where base has null/empty values.
    Never overwrite non-null base values.

    Returns (merged_data, merge_sources) where merge_sources lists
    which schema contributed which fields.
    """
    import json

    if not cluster:
        return {}, []

    # Sort by domain priority descending, then confidence descending
    sorted_results = sorted(
        cluster,
        key=lambda r: (_get_domain_priority(r), _get_confidence(r)),
        reverse=True,
    )

    base_result = sorted_results[0]
    base_data = base_result.get("extracted_data", {})
    if isinstance(base_data, str):
        try:
            base_data = json.loads(base_data)
        except (json.JSONDecodeError, TypeError):
            base_data = {}
    merged = dict(base_data) if base_data else {}

    base_schema = base_result.get("schema_name") or "unknown"
    base_conf = _get_confidence(base_result)
    sources = [{
        "schema_name": base_schema,
        "domain_slug": base_result.get("domain_slug", ""),
        "category_slug": base_result.get("category_slug", ""),
        "confidence": round(base_conf, 2),
        "role": "base",
    }]

    # Supplement from remaining results
    for r in sorted_results[1:]:
        r_data = r.get("extracted_data", {})
        if isinstance(r_data, str):
            try:
                r_data = json.loads(r_data)
            except (json.JSONDecodeError, TypeError):
                r_data = {}
        if not r_data:
            continue

        r_schema = r.get("schema_name") or "unknown"
        r_conf = _get_confidence(r)
        supplemented_fields = []

        for key, value in r_data.items():
            if key in merged and merged[key] is not None:
                # Don't overwrite if base has a real value
                # But do fill if base value is empty string or empty list
                existing = merged[key]
                if isinstance(existing, str) and existing.strip() == "":
                    merged[key] = value
                    supplemented_fields.append(key)
                elif isinstance(existing, list) and len(existing) == 0:
                    merged[key] = value
                    supplemented_fields.append(key)
                # Otherwise keep base value
            elif key not in merged:
                merged[key] = value
                supplemented_fields.append(key)

        sources.append({
            "schema_name": r_schema,
            "domain_slug": r.get("domain_slug", ""),
            "category_slug": r.get("category_slug", ""),
            "confidence": round(r_conf, 2),
            "role": "supplement",
            "fields_contributed": supplemented_fields,
        })

    return merged, sources


def select_and_merge_stage2(
    stage2_results: List[Dict[str, Any]],
    stage1_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Smart Stage 2 selection with entity-aware merging.

    1. Filter results below confidence 0.3
    2. Cluster by subject entity
    3. Pick primary cluster (prefer Immigration-domain)
    4. Merge within cluster (base = highest-priority-domain result)
    5. Return merged result with metadata

    Args:
        stage2_results: List of stage2 result dicts (with extracted_data,
                       confidence, domain_slug, category_slug, schema_name)
        stage1_data: Optional stage1 extraction data (unused currently,
                    reserved for future entity cross-reference)

    Returns:
        Dict with:
            - extracted_data: merged extraction
            - confidence: confidence of the base result
            - merge_info: {sources: [...], cluster_entity: str, merged: bool}
        Or None if no results
    """
    if not stage2_results:
        return None

    # Step 1: Filter below minimum confidence
    candidates = [
        r for r in stage2_results
        if _get_confidence(r) >= MIN_CONFIDENCE_THRESHOLD
    ]
    if not candidates:
        # Fall back to best single result
        return select_best_stage2(stage2_results)

    # Step 2: Cluster by entity
    clusters = _cluster_by_entity(candidates)

    # Step 3: Pick primary cluster
    cluster_entity, primary_cluster = _pick_primary_cluster(clusters)

    if not primary_cluster:
        return select_best_stage2(stage2_results)

    # Step 4: If only one result in cluster, no merge needed
    if len(primary_cluster) == 1:
        result = primary_cluster[0]
        return {
            "extracted_data": result.get("extracted_data"),
            "confidence": result.get("confidence"),
            "merge_info": {
                "sources": [{
                    "schema_name": result.get("schema_name", ""),
                    "domain_slug": result.get("domain_slug", ""),
                    "category_slug": result.get("category_slug", ""),
                    "confidence": round(_get_confidence(result), 2),
                    "role": "sole",
                }],
                "cluster_entity": cluster_entity,
                "merged": False,
            },
        }

    # Step 5: Merge within cluster
    merged_data, sources = _merge_extracted_data(primary_cluster)

    # Use the base result's confidence
    base_conf = _get_confidence(primary_cluster[0])
    # Adjust: use the max confidence from the immigration-domain results
    for r in primary_cluster:
        if _get_domain_priority(r) >= DOMAIN_PRIORITY["immigration"]:
            base_conf = max(base_conf, _get_confidence(r))
            break

    return {
        "extracted_data": merged_data,
        "confidence": round(base_conf, 2),
        "merge_info": {
            "sources": sources,
            "cluster_entity": cluster_entity,
            "merged": True,
            "schemas_merged": len(primary_cluster),
        },
    }
