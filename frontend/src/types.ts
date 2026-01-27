export interface Incident {
  id: string;
  date: string;
  state: string;
  city?: string;
  incident_type: string;
  victim_category?: string;
  outcome_category?: string;
  victim_name?: string;
  notes?: string;
  source_url?: string;
  source_name?: string;
  tier: number;
  lat?: number;
  lon?: number;
  is_non_immigrant: boolean;
  is_death: boolean;
  linked_ids?: string[];
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
  date_start?: string;
  date_end?: string;
}
