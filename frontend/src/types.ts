// Incident category discriminator
export type IncidentCategory = 'enforcement' | 'crime';

// Curation status
export type CurationStatus = 'pending' | 'in_review' | 'approved' | 'rejected';

// Victim categories
export type VictimCategory =
  | 'detainee'
  | 'enforcement_target'
  | 'protester'
  | 'journalist'
  | 'bystander'
  | 'us_citizen_collateral'
  | 'officer'
  | 'multiple';

// Outcome categories
export type OutcomeCategory =
  | 'death'
  | 'serious_injury'
  | 'minor_injury'
  | 'no_injury'
  | 'unknown';

export interface Incident {
  id: string;
  legacy_id?: string;
  category: IncidentCategory;
  date: string;
  state: string;
  city?: string;
  incident_type: string;
  victim_category?: VictimCategory;
  outcome_category?: OutcomeCategory;
  victim_name?: string;
  victim_age?: number;
  notes?: string;
  description?: string;
  source_url?: string;
  source_name?: string;
  tier: number;
  source_tier?: string;
  lat?: number;
  lon?: number;
  latitude?: number;
  longitude?: number;
  is_non_immigrant: boolean;
  is_death: boolean;
  linked_ids?: string[];
  severity_score?: number;

  // Sanctuary policy context
  state_sanctuary_status?: string;
  local_sanctuary_status?: string;
  detainer_policy?: string;

  // Crime-specific fields
  offender_immigration_status?: string;
  prior_deportations?: number;
  gang_affiliated?: boolean;

  // Curation workflow
  curation_status?: CurationStatus;
  extraction_confidence?: number;
}

export interface Stats {
  total_incidents: number;
  total_deaths: number;
  states_affected: number;
  non_immigrant_incidents: number;
  by_tier: Record<number, number>;
  by_state: Record<string, number>;
  by_incident_type: Record<string, number>;
}

export interface FilterOptions {
  states: string[];
  categories: string[];
  tiers: number[];
  date_min: string;
  date_max: string;
}

export interface Filters {
  tiers: number[];
  states: string[];
  categories: string[];
  non_immigrant_only: boolean;
  death_only?: boolean;
  date_start?: string;
  date_end?: string;
  // New unified filters
  incident_category?: IncidentCategory;
  incident_types?: string[];
  gang_affiliated?: boolean;
  prior_deportations_min?: number;
  search?: string;
}

// Admin types
export interface SourceInfo {
  name: string;
  enabled: boolean;
  tier: number;
  description: string;
}

export interface DataFileInfo {
  filename: string;
  tier: number;
  size_bytes: number;
  modified: string;
}

export interface AdminStatus {
  total_incidents: number;
  by_tier: Record<number, number>;
  by_source: Record<string, number>;
  available_sources: SourceInfo[];
  data_files: DataFileInfo[];
}

export interface PipelineResult {
  success: boolean;
  operation?: string;
  error?: string;
  fetched?: Record<string, number>;
  stats?: {
    original_counts: Record<number, number>;
    final_counts: Record<number, number>;
    validation_errors: number;
    duplicates_removed: number;
    geocoded: number;
    total: number;
  };
  processing_stats?: Record<string, unknown>;
  summary?: Record<string, unknown>;
}

// Person types (for crime tracking)
export interface Person {
  id: string;
  name?: string;
  aliases?: string[];
  age?: number;
  gender?: string;
  nationality?: string;
  immigration_status?: string;
  prior_deportations: number;
  reentry_after_deportation: boolean;
  gang_affiliated: boolean;
  gang_name?: string;
  prior_convictions: number;
  prior_violent_convictions: number;
  us_citizen?: boolean;
}

export interface IncidentPerson {
  id: string;
  incident_id: string;
  person_id: string;
  role: 'victim' | 'offender' | 'witness' | 'officer';
  notes?: string;
  person?: Person;
}

// Curation queue types
export interface CurationQueueItem {
  id: string;
  title?: string;
  content?: string;
  source_name?: string;
  source_url: string;
  published_date?: string;
  relevance_score?: number;
  extraction_confidence?: number;
  extracted_data?: ExtractedIncidentData;
  status: CurationStatus;
  fetched_at: string;
}

export interface ExtractedIncidentData {
  date?: string;
  date_confidence?: number;
  state?: string;
  state_confidence?: number;
  city?: string;
  city_confidence?: number;
  incident_type?: string;
  incident_type_confidence?: number;
  victim_name?: string;
  victim_name_confidence?: number;
  victim_age?: number;
  victim_category?: VictimCategory;
  victim_category_confidence?: number;
  outcome_category?: OutcomeCategory;
  outcome_category_confidence?: number;
  offender_name?: string;
  description?: string;
  outcome?: string;
  immigration_status?: string;
  prior_deportations?: number;
  gang_affiliated?: boolean;
  overall_confidence?: number;
}

export interface CurationDecision {
  action: 'approve' | 'reject';
  rejection_reason?: string;
  incident_overrides?: Partial<ExtractedIncidentData>;
}

// Comparison stats for cross-category analysis
export interface ComparisonStats {
  enforcement_incidents: number;
  crime_incidents: number;
  enforcement_deaths: number;
  crime_deaths: number;
  by_jurisdiction: JurisdictionComparison[];
}

export interface JurisdictionComparison {
  name: string;
  state_code?: string;
  sanctuary_status?: string;
  enforcement_incidents: number;
  crime_incidents: number;
  enforcement_deaths: number;
  crime_deaths: number;
}

// Job Queue types
export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type JobType = 'fetch' | 'process' | 'batch_extract' | 'batch_enrich' | 'full_pipeline';

export interface Job {
  id: string;
  job_type: JobType;
  status: JobStatus;
  progress?: number;
  total?: number;
  message?: string;
  params?: Record<string, unknown>;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

// Settings types
export interface AutoApprovalSettings {
  min_confidence_auto_approve: number;
  min_confidence_review: number;
  auto_reject_below: number;
  required_fields: string[];
  field_confidence_threshold: number;
  min_severity_auto_approve: number;
  max_severity_auto_reject: number;
  enable_auto_approve: boolean;
  enable_auto_reject: boolean;
  enforcement_confidence_threshold: number;
  crime_confidence_threshold: number;
}

export interface DuplicateDetectionSettings {
  title_similarity_threshold: number;
  content_similarity_threshold: number;
  entity_match_date_window: number;
  shingle_size: number;
  enable_url_match: boolean;
  enable_title_match: boolean;
  enable_content_match: boolean;
  enable_entity_match: boolean;
}

export interface PipelineSettings {
  enable_llm_extraction: boolean;
  enable_duplicate_detection: boolean;
  enable_auto_approval: boolean;
  batch_size: number;
  delay_between_articles_ms: number;
  max_article_length: number;
  default_source_tier: number;
}

export interface AllSettings {
  auto_approval: AutoApprovalSettings;
  duplicate_detection: DuplicateDetectionSettings;
  pipeline: PipelineSettings;
}

// Feed types
export interface Feed {
  id: string;
  name: string;
  url: string;
  feed_type: string;
  interval_minutes: number;
  active: boolean;
  last_fetched?: string;
  created_at?: string;
}

// Analytics types
export interface OverviewStats {
  total_incidents: number;
  enforcement_incidents: number;
  crime_incidents: number;
  total_deaths: number;
  states_affected: number;
  queue_stats: Record<string, number>;
  ingested_total: number;
  approved_total: number;
  rejected_total: number;
  pending_review: number;
}

export interface FunnelStage {
  stage: string;
  count: number;
}

export interface SourceStats {
  source_name: string;
  total: number;
  approved: number;
  rejected: number;
  avg_confidence: number | null;
  approval_rate: number;
}

export interface StateStats {
  state: string;
  total: number;
  enforcement: number;
  crime: number;
  deaths: number;
}

// Confidence tier types
export type ConfidenceTier = 'high' | 'medium' | 'low';

export interface TieredQueueItem {
  id: string;
  title?: string;
  source_name?: string;
  extraction_confidence: number | null;
  published_date?: string;
  fetched_at?: string;
}

export interface TieredQueue {
  high: TieredQueueItem[];
  medium: TieredQueueItem[];
  low: TieredQueueItem[];
}

export interface AISuggestion {
  field: string;
  current_value: unknown;
  confidence: number;
  suggestion: unknown;
  reason: string;
}
