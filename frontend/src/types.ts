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

// Source/article linked to an incident
export interface IncidentSource {
  id: string;
  url: string;
  title?: string;
  source_name?: string;
  published_date?: string;
  is_primary: boolean;
  created_at?: string;
}

export interface Incident {
  id: string;
  legacy_id?: string;
  category: IncidentCategory;
  date: string;
  state: string;
  state_name?: string;
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

  // Multiple sources for this incident
  sources?: IncidentSource[];

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

  // Extensibility system — populated by detail endpoints
  actors?: IncidentActor[];
  linked_events?: IncidentEvent[];
  domain_name?: string;
  domain_slug?: string;
  category_name?: string;
  category_slug?: string;
}

export interface IncidentActor {
  id: string;
  canonical_name: string;
  actor_type: string;
  role: string;
  role_type?: string;
  role_type_name?: string;
  is_primary: boolean;
  immigration_status?: string;
  nationality?: string;
  gender?: string;
  is_law_enforcement: boolean;
  prior_deportations?: number;
}

export interface IncidentEvent {
  id: string;
  name: string;
  event_type?: string;
  start_date?: string;
  description?: string;
  is_primary_event?: boolean;
}

export interface PipelineStats {
  articles_ingested: number;
  pending_review: number;
  domains_active: number;
  events_tracked: number;
  avg_extraction_confidence: number | null;
}

export interface IncidentStats {
  fatal_outcomes: number;
  serious_injuries: number;
  domain_counts: Record<string, number>;
  events_tracked: number;
  avg_confidence: number | null;
}

export interface Stats {
  total_incidents: number;
  total_deaths: number;
  states_affected: number;
  non_immigrant_incidents: number;
  by_category: Record<string, number>;
  category_deaths: Record<string, number>;
  by_tier: Record<number, number>;
  by_state: Record<string, number>;
  by_incident_type: Record<string, number>;
  pipeline_stats?: PipelineStats | null;
  incident_stats?: IncidentStats | null;
}

// Connected incidents types
export interface ConnectedIncidentSummary {
  id: string;
  date: string | null;
  city: string | null;
  state: string | null;
  incident_type: string | null;
  outcome_category: string | null;
  victim_name: string | null;
}

export interface EventConnection {
  event_id: string;
  event_name: string;
  event_slug: string;
  incidents: ConnectedIncidentSummary[];
}

export interface IncidentConnections {
  incident_id: string;
  events: EventConnection[];
}

export interface EventListItem {
  id: string;
  name: string;
  event_type?: string;
  incident_count: number;
}

export interface DomainCategory {
  id: string;
  name: string;
  slug: string;
}

export interface DomainSummary {
  id: string;
  name: string;
  slug: string;
  categories: DomainCategory[];
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
  date_start?: string;
  date_end?: string;
  // Domain/category taxonomy filters
  domain?: string;
  category?: string;
  severity?: string;
  event_id?: string;
  // Unified filters
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
  category?: IncidentCategory;
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
  // Offender details for crime incidents
  offender_name?: string;
  offender_name_confidence?: number;
  offender_age?: number;
  offender_gender?: string;
  offender_nationality?: string;
  offender_country_of_origin?: string;
  immigration_status?: string;
  entry_method?: string;
  prior_deportations?: number;
  prior_arrests?: number;
  prior_convictions?: number;
  gang_affiliated?: boolean;
  gang_name?: string;
  cartel_connection?: string;
  ice_detainer_ignored?: boolean;
  was_released_sanctuary?: boolean;
  was_released_bail?: boolean;
  // Crime victim details
  crime_victim_count?: number;
  crime_victim_names?: string[];
  involves_fatality?: boolean;
  // Legal details
  charges?: string[];
  sentence?: string;
  // Common fields
  description?: string;
  outcome?: string;
  overall_confidence?: number;
  extraction_notes?: string;
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
  retry_count?: number;
  max_retries?: number;
  queue?: string;
  priority?: number;
  celery_task_id?: string;
}

export interface QueueMetrics {
  queues: Record<string, { active: number; reserved: number; workers: string[] }>;
  workers: Record<string, { status: string; active_tasks: number; tasks_completed: number }>;
  totals: { active_tasks: number; reserved_tasks: number; total_workers: number };
  error?: string;
}

export interface JobStageProgress {
  name: string;
  label: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress?: number;
  total?: number;
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

export interface EventClusteringSettings {
  max_distance_km: number;
  require_coordinates: boolean;
  max_time_window_days: number;
  require_same_incident_type: boolean;
  require_same_category: boolean;
  min_cluster_size: number;
  min_confidence_threshold: number;
  enable_ai_similarity: boolean;
  ai_similarity_threshold: number;
  enable_actor_matching: boolean;
}

export interface AllSettings {
  auto_approval: AutoApprovalSettings;
  duplicate_detection: DuplicateDetectionSettings;
  pipeline: PipelineSettings;
  event_clustering: EventClusteringSettings;
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

// =====================
// Extensible System Types
// =====================

// Incident Types
export type FieldType = 'string' | 'text' | 'integer' | 'decimal' | 'boolean' | 'date' | 'datetime' | 'enum' | 'array' | 'reference';

export interface FieldDefinition {
  id: string;
  name: string;
  display_name: string;
  field_type: FieldType;
  description?: string;
  required: boolean;
  enum_values?: string[];
  extraction_hint?: string;
  display_order: number;
  show_in_list: boolean;
  show_in_detail: boolean;
}

export interface IncidentType {
  id: string;
  name: string;
  slug: string;
  display_name: string;
  description?: string;
  category: IncidentCategory;
  icon?: string;
  color?: string;
  is_active: boolean;
  severity_weight: number;
  approval_thresholds?: Record<string, number>;
  validation_rules?: unknown[];
  fields?: FieldDefinition[];
  pipeline_config?: PipelineStageConfig[];
}

export interface PipelineStageConfig {
  id: string;
  stage_id: string;
  enabled: boolean;
  execution_order?: number;
  stage_config: Record<string, unknown>;
}

export interface PipelineStage {
  id: string;
  name: string;
  slug: string;
  description?: string;
  default_order: number;
  is_active: boolean;
}

// Prompts
export type PromptType = 'extraction' | 'classification' | 'entity_resolution' | 'pattern_detection' | 'summarization' | 'analysis';
export type PromptStatus = 'draft' | 'active' | 'testing' | 'deprecated' | 'archived';

export interface Prompt {
  id: string;
  name: string;
  slug: string;
  description?: string;
  prompt_type: PromptType;
  incident_type_id?: string;
  system_prompt: string;
  user_prompt_template: string;
  output_schema?: Record<string, unknown>;
  version: number;
  status: PromptStatus;
  model_name: string;
  max_tokens: number;
  temperature: number;
  traffic_percentage: number;
  ab_test_group?: string;
  created_at: string;
  activated_at?: string;
  version_history?: PromptVersion[];
}

export interface PromptVersion {
  id: string;
  version: number;
  status: PromptStatus;
  created_at: string;
}

export interface PromptExecutionStats {
  total_executions: number;
  successful: number;
  failed: number;
  success_rate: number;
  avg_latency_ms?: number;
  avg_input_tokens?: number;
  avg_output_tokens?: number;
  avg_confidence?: number;
}

// Events
export interface Event {
  id: string;
  name: string;
  slug?: string;
  description?: string;
  event_type?: string;
  start_date: string;
  end_date?: string;
  ongoing: boolean;
  primary_state?: string;
  primary_city?: string;
  geographic_scope?: string;
  latitude?: number;
  longitude?: number;
  ai_summary?: string;
  tags: string[];
  incident_count: number;
  incidents?: EventIncident[];
  actors?: EventActor[];
}

export interface EventIncident {
  incident_id: string;
  date?: string;
  state?: string;
  city?: string;
  category?: string;
  incident_type?: string;
  incident_type_display?: string;
  description?: string;
  victim_name?: string;
  outcome_category?: string;
  notes?: string;
  is_primary_event?: boolean;
  sequence_number?: number;
}

export interface EventActor {
  id: string;
  canonical_name: string;
  actor_type: ActorType;
  aliases?: string[];
  is_law_enforcement?: boolean;
  role: ActorRole;
  incident_count: number;
}

export interface EventSuggestion {
  incident_ids: string[];
  suggested_name: string;
  event_type: string;
  start_date: string;
  end_date: string;
  primary_state: string;
  primary_city?: string;
  incident_type: string;
  category: string;
  incident_count: number;
  confidence: number;
  reasoning: string[];
  center_lat?: number;
  center_lon?: number;
}

// Actors
export type ActorType = 'person' | 'organization' | 'agency' | 'group';
export type ActorRole = 'victim' | 'offender' | 'witness' | 'officer' | 'arresting_agency' | 'reporting_agency' | 'bystander' | 'organizer' | 'participant';
export type ActorRelationType = 'alias_of' | 'member_of' | 'affiliated_with' | 'employed_by' | 'family_of' | 'associated_with';

export interface Actor {
  id: string;
  canonical_name: string;
  actor_type: ActorType;
  aliases: string[];
  date_of_birth?: string;
  date_of_death?: string;
  gender?: string;
  nationality?: string;
  immigration_status?: string;
  prior_deportations: number;
  organization_type?: string;
  is_government_entity: boolean;
  is_law_enforcement: boolean;
  jurisdiction?: string;
  description?: string;
  confidence_score?: number;
  incident_count: number;
  roles_played: string[];
  incidents?: ActorIncident[];
  relations?: ActorRelation[];
}

export interface ActorIncident {
  incident_id: string;
  date?: string;
  state?: string;
  city?: string;
  category?: string;
  incident_type?: string;
  description?: string;
  role: ActorRole;
}

export interface ActorRelation {
  id: string;
  related_actor_id: string;
  relation_type: ActorRelationType;
  confidence?: number;
}

export interface ActorMergeSuggestion {
  actor1_id: string;
  actor1_name: string;
  actor2_id: string;
  actor2_name: string;
  similarity: number;
  reason: string;
}

// Pipeline Execution
export interface PipelineExecutionResult {
  success: boolean;
  article_id?: string;
  stages_completed: string[];
  final_decision?: string;
  decision_reason?: string;
  total_duration_ms: number;
  error?: string;
  context?: {
    detected_category?: string;
    detected_actors: DetectedActor[];
    detected_relations: DetectedRelation[];
    validation_errors: string[];
  };
}

export interface DetectedActor {
  actor_id?: string;
  canonical_name?: string;
  extracted_name: string;
  role: ActorRole;
  match_type: 'existing' | 'created' | 'pending';
  similarity?: number;
  confidence?: number;
}

export interface DetectedRelation {
  type: string;
  incident_id?: string;
  event_id?: string;
  relation_type?: string;
  reason?: string;
  match_score?: number;
}

// Universal extraction format (from LLM universal extractor)
export interface ExtractedActor {
  name: string;
  name_confidence?: number;
  actor_type: 'person' | 'agency' | 'group';
  roles: string[];
  age?: number;
  gender?: string;
  nationality?: string;
  country_of_origin?: string;
  immigration_status?: string;
  prior_deportations?: number;
  prior_criminal_history?: boolean;
  gang_affiliation?: string;
  agency_type?: string;
  charges?: string[];
  sentence?: string;
  injuries?: string;
  action_taken?: string;
  notes?: string;
}

export interface ExtractedEvent {
  date?: string;
  event_type: string;
  description: string;
  relation_to_incident?: string;
}

export interface ExtractedIncidentInfo {
  date?: string;
  title?: string;
  summary?: string;
  location?: {
    city?: string;
    state?: string;
    county?: string;
    address?: string;
    location_type?: string;
  };
  outcome?: {
    severity?: string;
    description?: string;
  };
  categories?: string[];
  incident_types?: string[];
  date_confidence?: number;
  date_approximate?: boolean;
  overall_confidence?: number;
  location_confidence?: number;
}

export interface ExtractedPolicyContext {
  policy_mentioned?: string;
  ice_detainer_status?: string;
  sanctuary_jurisdiction?: boolean;
}

export interface UniversalExtractionData {
  success?: boolean;
  is_relevant?: boolean;
  isRelevant?: boolean;
  relevance_reason?: string;
  confidence?: number;
  categories?: string[];
  extraction_type?: string;
  extraction_notes?: string;
  sources_cited?: string[];
  incident?: ExtractedIncidentInfo;
  actors?: ExtractedActor[];
  events?: ExtractedEvent[];
  policy_context?: ExtractedPolicyContext;
  // Legacy flat fields (for backward compat)
  [key: string]: unknown;
}
