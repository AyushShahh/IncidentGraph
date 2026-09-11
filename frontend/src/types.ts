export interface ServiceHealthItem {
  name: string;
  url: string;
  type: 'microservice' | 'infrastructure';
  status: 'healthy' | 'degraded' | 'down';
  latency_ms: number;
  details?: Record<string, any>;
  last_checked?: string;
}

export interface SystemHealthResponse {
  status: string;
  services: ServiceHealthItem[];
  timestamp: string;
}

export interface IncidentCandidate {
  id: string;
  fingerprint: string;
  service_name: string;
  normalized_text: string;
  error_code?: string;
  occurrence_count: number;
  first_seen: string;
  last_seen: string;
}

export interface Incident {
  id: string;
  title: string;
  status: 'ACTIVE' | 'INVESTIGATING' | 'AWAITING_APPROVAL' | 'RESOLVED' | 'REJECTED' | 'SUPPRESSED';
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  primary_service: string;
  affected_services: string[];
  total_occurrences: number;
  first_seen: string;
  last_seen: string;
  representative_log?: Record<string, any>;
  summary?: string;
  candidates?: IncidentCandidate[];
  resolution?: Record<string, any>;
}

export interface EvidenceItem {
  evidence_id: string;
  source_tool: string;
  file_path?: string;
  line_range?: string;
  code_snippet?: string;
  finding_summary: string;
  relevance: string;
}

export interface FinalReport {
  root_cause: string;
  suggested_fix: string;
  blast_radius?: {
    primary_service?: string;
    affected_services?: string[];
    transitive_impacts?: string[];
    risk_score?: number;
  };
  evidence?: EvidenceItem[];
  reasoning_summary?: string;
  inspected_files?: string[];
  inspected_symbols?: string[];
  references?: string[];
  confidence?: number;
}

export interface Hypothesis {
  root_cause_statement: string;
  failure_mechanism: string;
  affected_component: string;
  confidence: number;
  has_enough_evidence: boolean;
}

export interface ReviewResult {
  root_cause_validated: boolean;
  approved_for_fix: boolean;
  evidence_quality_score: number;
  critique: string;
  recommendations: string[];
}

export interface InvestigationDetail {
  incident_id: string;
  status: string;
  approval_status: 'INVESTIGATING' | 'AWAITING_APPROVAL' | 'APPROVED' | 'REJECTED';
  confidence: number;
  iterations: number;
  tokens_used?: number;
  final_report?: FinalReport;
  hypothesis?: Hypothesis;
  review_result?: ReviewResult;
  evidence?: EvidenceItem[];
  visited_files?: string[];
  visited_symbols?: string[];
  initial_context?: Record<string, any>;
  current_plan?: Record<string, any>;
  source?: string;
}

export interface PlatformStats {
  total_incidents: number;
  active_incidents: number;
  resolved_incidents: number;
  total_occurrences: number;
  auto_resolution_rate?: number;
  auto_resolve_rate_percent?: number;
  avg_latency_ms?: number;
  total_services?: number;
  healthy_services?: number;
}

export interface FeedEvent {
  id: string;
  type: string;
  timestamp: string;
  service?: string;
  message: string;
  severity?: string;
  incident_id?: string;
  data?: Record<string, any>;
}

export interface GraphNode {
  id: string;
  label: string;
  type: 'service' | 'database' | 'queue';
  status?: 'healthy' | 'warning' | 'critical';
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  call_count?: number;
  type?: string;
}

export interface DependencyGraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
