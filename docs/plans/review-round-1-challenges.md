# Challenge Report: Generic Event Tracking System - Architecture Plan

## Summary
- Document Type: Technical Architecture Plan
- Review Round: 1
- Critical Issues: 7
- Major Issues: 12
- Minor Issues: 8

## Critical Challenges

### [C-001] [Critical] JSONB Performance Impact Unquantified

**Dimension**: Technical Feasibility

**Challenge**: The plan relies heavily on JSONB for custom_fields with GIN indexes as the primary mitigation, but provides no performance benchmarking, capacity planning, or quantified acceptance criteria. What evidence supports that JSONB queries will meet the stated "<500ms for 95th percentile" requirement at scale?

**Evidence**:
- Line 1407: "Add GIN indexes, monitor query times" - vague mitigation
- Line 1463: "JSONB performance degradation | High | Medium" - acknowledged but not addressed
- Line 1478: "Query performance < 500ms for 95th percentile" - no baseline or projection

**Required Response**:
- Benchmark JSONB query performance with realistic data volumes (10K, 100K, 1M+ incidents)
- Provide specific query patterns that will be used and their measured performance
- Define fallback strategy if JSONB proves inadequate (e.g., materialized columns, schema evolution)
- Quantify acceptable performance degradation threshold that triggers schema changes

### [C-002] [Critical] Migration Rollback Strategy Missing

**Dimension**: Risk Assessment

**Challenge**: The plan acknowledges "Migration data loss | Critical | Low" but provides no detailed rollback plan, data integrity verification, or recovery procedures. What is the step-by-step rollback procedure if migration fails midway through Phase 1?

**Evidence**:
- Lines 1279-1311: Migration steps show forward path only
- No transaction boundaries defined
- No rollback SQL provided
- No data integrity verification checksums

**Required Response**:
- Document complete rollback procedure for each migration phase
- Provide rollback SQL scripts
- Define data integrity verification (checksums, row counts, foreign key validation)
- Specify rollback time window (can you roll back after 1 week? 1 month?)
- Define point-of-no-return for each phase

### [C-003] [Critical] Concurrent Access During Migration Undefined

**Dimension**: Technical Feasibility

**Challenge**: The migration strategy doesn't address how the system remains operational during schema changes. Can users continue creating incidents while taxonomy tables are being populated? What happens if an incident references a category_id that's being migrated?

**Evidence**:
- Line 1242: "Minimize risk by keeping existing system operational"
- Lines 1292-1297: UPDATE statements with no locking strategy
- No mention of downtime windows, read-only modes, or data consistency guarantees

**Required Response**:
- Define whether migrations require downtime or zero-downtime approach
- Specify locking strategy (row-level, table-level, none)
- Document transaction isolation levels during migration
- Provide concurrent access testing plan
- Define what happens to in-flight transactions during migration

### [C-004] [Critical] LLM Prompt Versioning and Testing Strategy Absent

**Dimension**: Technical Feasibility

**Challenge**: The extraction_schemas table stores prompts in the database with versioning (schema_version), but there's no CI/CD pipeline for testing prompt changes, no A/B testing framework, and no rollback for bad prompts. How do you validate a prompt change won't degrade extraction quality across 1000s of articles?

**Evidence**:
- Lines 456-526: extraction_schemas table definition
- Line 462: schema_version INTEGER but no version control integration
- No mention of prompt testing, validation, or quality metrics

**Required Response**:
- Define prompt testing framework (golden dataset, expected outputs)
- Specify prompt validation before production deployment
- Document how to detect prompt quality degradation in production
- Provide prompt rollback mechanism
- Define quality metrics for prompt performance (precision, recall, F1)

### [C-005] [Critical] Cross-Domain Referential Integrity Violations

**Dimension**: Technical Feasibility

**Challenge**: The schema allows incidents to reference categories, but if a domain is deactivated (is_active=FALSE), what happens to its incidents? The plan shows CASCADE deletes for categories but doesn't address domain-level operations or cross-domain actor references.

**Evidence**:
- Line 108: `ON DELETE CASCADE` for event_categories
- Line 99: `is_active BOOLEAN DEFAULT TRUE` for domains
- No discussion of archiving, soft deletes, or domain deprecation

**Required Response**:
- Define behavior when domain is deactivated (archive incidents? prevent deactivation?)
- Specify actor consistency across domains (prosecutor in criminal justice referenced in civil rights case)
- Document foreign key cascade behavior and edge cases
- Provide domain deprecation workflow

### [C-006] [Critical] Timeline Estimation Methodology Undefined

**Dimension**: Organizational Feasibility

**Challenge**: "12-16 weeks for core implementation" appears at line 19 with no supporting work breakdown, velocity assumptions, team size, or dependency analysis. How was this estimate derived?

**Evidence**:
- Line 19: "12-16 weeks" - no justification
- Lines 1249-1275: Phase breakdown shows tasks but no hour estimates
- No team capacity, skill requirements, or parallelization analysis

**Required Response**:
- Provide detailed work breakdown with hour estimates per task
- Specify team size and skill requirements (backend devs, DB admins, frontend devs)
- Document assumptions (velocity, hours per week, blockers)
- Identify critical path and dependencies
- Define what "core implementation" includes vs. excludes

### [C-007] [Critical] Backward Compatibility Validation Missing

**Dimension**: Risk Assessment

**Challenge**: The plan states "Maintain backward compatibility with existing immigration tracking" (line 14) but provides no automated testing, API contract validation, or regression tests to verify this. How do you prove backward compatibility is maintained?

**Evidence**:
- Line 14: Promise of backward compatibility
- Line 1253: "Test backward compatibility" - no specifics
- Lines 170-186: Migration that changes core incident structure
- No mention of API versioning or contract tests

**Required Response**:
- Define backward compatibility scope (which APIs, which queries, which features)
- Provide regression test suite that validates immigration workflows unchanged
- Document API versioning strategy if breaking changes needed
- Specify deprecation timeline for old columns (e.g., category enum)
- Define what "compatible" means quantitatively (zero errors? <5% performance degradation?)

## Major Challenges

### [M-001] [Major] Actor Role Type Migration Data Loss Risk

**Dimension**: Technical Feasibility

**Challenge**: Lines 251-254 show a REGEX-based migration from free-text role to role_type_id, which will fail for any role not matching the seeded slugs. What happens to custom roles that don't match?

**Evidence**:
```sql
UPDATE incident_actors SET role_type_id = (
    SELECT id FROM actor_role_types
    WHERE slug = LOWER(REGEXP_REPLACE(incident_actors.role, '[^a-zA-Z0-9]+', '_', 'g'))
) WHERE role_type_id IS NULL;
```

**Required Response**: Pre-migration audit of unique roles, strategy for unmapped roles, data validation query

### [M-002] [Major] Extraction Schema Field Definition Format Unspecified

**Dimension**: Requirements Clarity

**Challenge**: The field_definitions JSONB column (line 476) stores field metadata but the schema is undefined. What's the difference between field_definitions and required_fields/optional_fields? Can validators be arbitrary code?

**Evidence**: Lines 476-477, 514-524 show example but no formal schema definition

**Required Response**: JSON Schema for field_definitions, validation rule format specification, security constraints on custom validators

### [M-003] [Major] Recidivism Risk Algorithm Lacks Scientific Basis

**Dimension**: Technical Feasibility

**Challenge**: The calculate_recidivism_risk function (lines 582-616) uses arbitrary coefficients (0.1, 100, 0.3) with a comment "replace with ML model later". This is a critical feature with no validation.

**Evidence**: Line 602: "Simple risk model (replace with ML model later)"

**Required Response**: Either provide evidence-based algorithm or remove feature until proper model available, define acceptable error rates, document limitations

### [M-004] [Major] Case Number Uniqueness Not Enforced Across Jurisdictions

**Dimension**: Technical Feasibility

**Challenge**: The cases table has UNIQUE(case_number) but doesn't account for different jurisdictions using the same case numbers. Case "CR-2026-001" could exist in multiple courts.

**Evidence**: Line 314: `case_number VARCHAR(100) UNIQUE`

**Required Response**: Change to UNIQUE(case_number, jurisdiction_id) or define case_number format requirements

### [M-005] [Major] Event Relationship Cycle Detection Missing

**Dimension**: Technical Feasibility

**Challenge**: The event_relationships table allows 'precedes'/'follows' relationships but has no cycle detection. Event A → B → C → A would create invalid temporal loops.

**Evidence**: Lines 262-302 show relationship schema with no cycle prevention

**Required Response**: Add CHECK constraint or trigger to prevent cycles, define maximum relationship chain depth, document graph traversal algorithms

### [M-006] [Major] Custom Field Validation Not Enforced at Write

**Dimension**: Technical Feasibility

**Challenge**: Categories define required_fields/optional_fields (line 118-120) but there's no enforcement mechanism shown. Can incidents be created with missing required custom fields?

**Evidence**: No trigger, constraint, or application-level validation shown

**Required Response**: Implement validation trigger or application-level enforcement, define error handling for validation failures

### [M-007] [Major] Materialized View Refresh Strategy Undefined

**Dimension**: Completeness

**Challenge**: Multiple materialized views are created (prosecutor_stats line 431, recidivism_analysis line 561) but refresh strategy is vague. How often? Automatic or manual? What about query inconsistency during refresh?

**Evidence**: Line 1411: "REFRESH MATERIALIZED VIEW CONCURRENTLY" - when? how often?

**Required Response**: Define refresh frequency, automatic vs manual, staleness tolerance, monitoring for refresh failures

### [M-008] [Major] No Discussion of Transaction Boundaries for Multi-Table Operations

**Dimension**: Technical Feasibility

**Challenge**: Creating a case involves multiple tables (cases, case_incidents, case_actors) but transaction boundaries aren't specified. What if case creation succeeds but case_actors insert fails?

**Evidence**: Lines 693-699 show multi-step operation with no transaction handling

**Required Response**: Define transaction boundaries for all multi-table operations, specify isolation levels, document retry/rollback behavior

### [M-009] [Major] Geographic Data Model Inadequate for Multi-Jurisdiction Cases

**Dimension**: Requirements Clarity

**Challenge**: Federal cases, multi-state crimes, and appeals cross jurisdictional boundaries, but the schema has single jurisdiction_id and state fields. How do you model a case that spans multiple states?

**Evidence**: Line 316: `jurisdiction_id UUID` (singular), incidents.state VARCHAR (singular)

**Required Response**: Support multi-jurisdiction cases, define primary vs. related jurisdictions, document how this affects analytics

### [M-010] [Major] Extraction Confidence Calculation Algorithm Too Simplistic

**Dimension**: Technical Feasibility

**Challenge**: The _calculate_confidence method (lines 832-848) uses only field completeness, ignoring LLM confidence scores, field importance weighting, or cross-field validation.

**Evidence**: Line 839: `filled_required / len(required_fields)` - naive calculation

**Required Response**: Incorporate LLM confidence scores, weight critical fields higher, validate against domain-specific rules

### [M-011] [Major] No Data Retention or Archival Policy

**Dimension**: Completeness

**Challenge**: The plan doesn't address data growth over years. Do incidents ever get archived? Deleted? What about GDPR/privacy concerns for actor PII?

**Evidence**: No mention of retention, archival, or data lifecycle

**Required Response**: Define retention policy, archival strategy, legal compliance requirements (GDPR, CCPA)

### [M-012] [Major] Frontend Error Handling for Dynamic Forms Unspecified

**Dimension**: Requirements Clarity

**Challenge**: The DynamicIncidentForm (lines 1087-1166) renders fields based on category schemas but doesn't show validation, error states, or handling of malformed field definitions.

**Evidence**: No validation, error handling, or schema load failures addressed

**Required Response**: Define client-side validation, error messaging, handling of missing/malformed schemas

## Minor Challenges

### [m-001] [Minor] Display Order Ties Unresolved

**Dimension**: Requirements Clarity

**Challenge**: Tables use display_order INTEGER but don't specify tie-breaking behavior. What if two categories have display_order=1?

**Evidence**: Lines 100, 114

**Required Response**: Define tie-breaking (alphabetical? creation date? arbitrary?)

### [m-002] [Minor] Color Validation Missing

**Dimension**: Requirements Clarity

**Challenge**: event_domains.color is VARCHAR(7) presumably for hex colors but no CHECK constraint validates format.

**Evidence**: Line 98

**Required Response**: Add CHECK constraint `color ~ '^#[0-9A-Fa-f]{6}$'`

### [m-003] [Minor] Timestamp Precision Inconsistent

**Dimension**: Technical Feasibility

**Challenge**: date_precision field (line 176) allows 'time' but event_start_date is DATE type, not TIMESTAMPTZ.

**Evidence**: Lines 174-176

**Required Response**: Change to TIMESTAMPTZ or document why DATE is sufficient

### [m-004] [Minor] Actor Type Constraint Missing

**Dimension**: Technical Feasibility

**Challenge**: The prosecutor_stats view filters on actor_type='prosecutor' (line 445) but actors table schema isn't shown - is this column validated?

**Evidence**: Line 445 references actors.actor_type not defined in migrations

**Required Response**: Show actors table schema or reference existing schema documentation

### [m-005] [Minor] Case Status Enum Not Enforced

**Dimension**: Technical Feasibility

**Challenge**: cases.status is VARCHAR with comment showing expected values but no CHECK constraint.

**Evidence**: Line 320: `status VARCHAR(50) NOT NULL DEFAULT 'active'` with comment

**Required Response**: Add CHECK constraint or use ENUM type

### [m-006] [Minor] Frontend TypeScript Types Don't Match Backend Schema

**Dimension**: Requirements Clarity

**Challenge**: TypeScript interfaces (lines 1019-1038) use camelCase but database columns are snake_case. Is there a conversion layer?

**Evidence**: `categoryCount` vs `category_count`

**Required Response**: Document serialization layer, provide conversion utilities

### [m-007] [Minor] No Discussion of API Pagination

**Dimension**: Completeness

**Challenge**: Endpoints like `/api/domains` and `/api/prosecutors/stats` could return large result sets but no pagination is shown.

**Evidence**: Lines 899-915, 1186-1234

**Required Response**: Add pagination parameters, document default page sizes

### [m-008] [Minor] Test Coverage Metric Unrealistic

**Dimension**: Requirements Clarity

**Challenge**: "100% test coverage for core domain logic" (line 1482) is aspirational but typically unachievable and not cost-effective.

**Evidence**: Line 1482

**Required Response**: Define realistic coverage target (e.g., 80% line coverage, 100% critical path coverage)
