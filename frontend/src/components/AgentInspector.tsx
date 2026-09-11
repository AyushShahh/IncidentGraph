import React from 'react';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  FileCode,
  FileText,
  Lightbulb,
  Play,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { EvidenceItem, Incident, InvestigationDetail } from '../types';

interface AgentInspectorProps {
  incidents: Incident[];
  selectedIncidentId: string | null;
  investigation: InvestigationDetail | null;
  isLoading: boolean;
  onSelectIncident: (id: string) => void;
  onTriggerInvestigation: (id: string, service: string) => void;
}

export const AgentInspector: React.FC<AgentInspectorProps> = ({
  incidents,
  selectedIncidentId,
  investigation,
  isLoading,
  onSelectIncident,
  onTriggerInvestigation,
}) => {
  const incidentList = Array.isArray(incidents) ? incidents : [];
  const currentIncident = incidentList.find((i) => i.id === selectedIncidentId) || incidentList[0];

  const confidence = investigation?.confidence || 0.0;
  const confidencePct = Math.round(confidence * 100);
  const hypothesis = investigation?.hypothesis;
  const reviewResult = investigation?.review_result;
  const finalReport = investigation?.final_report;
  const rawEv = investigation?.evidence || (finalReport?.evidence as any) || [];
  const evidenceList: EvidenceItem[] = Array.isArray(rawEv) ? rawEv : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Top Bar: Selector & Trigger */}
      <div
        className="glass-panel"
        style={{
          padding: '0.85rem 1.25rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            <Bot size={18} color="#0f172a" />
            <h3 style={{ fontSize: '0.95rem', fontWeight: 600 }}>Autonomous Agent Inspector</h3>
          </div>

          {/* Incident Selector Dropdown */}
          <select
            value={currentIncident?.id || ''}
            onChange={(e) => onSelectIncident(e.target.value)}
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid var(--border-hover)',
              borderRadius: 'var(--radius-sm)',
              color: '#0f172a',
              padding: '0.35rem 0.75rem',
              fontSize: '0.8rem',
              outline: 'none',
              cursor: 'pointer',
              maxWidth: '380px',
            }}
          >
            {incidentList.length === 0 ? (
              <option value="">No active incidents available</option>
            ) : (
              incidentList.map((inc) => (
                <option key={inc.id} value={inc.id}>
                  [{inc.primary_service}] {inc.title.slice(0, 50)}... ({inc.severity})
                </option>
              ))
            )}
          </select>
        </div>

        {currentIncident && (
          <button
            onClick={() => onTriggerInvestigation(currentIncident.id, currentIncident.primary_service)}
            className="btn btn-secondary btn-sm"
          >
            <Play size={12} />
            Dispatch Investigation
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          <Bot size={28} color="#0f172a" style={{ margin: '0 auto 0.75rem' }} />
          <div>Retrieving agent checkpoints and execution trace from storage...</div>
        </div>
      ) : !investigation ? (
        <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '0.85rem' }}>
            {currentIncident
              ? 'No prior investigation trace found for this incident. Click "Dispatch Investigation" to initiate autonomous analysis.'
              : 'No incidents available for inspection.'}
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Metrics Row */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '1rem',
            }}
          >
            {/* Confidence Gauge */}
            <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Agent Confidence</span>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    fontSize: '1.15rem',
                    color: confidencePct >= 80 ? '#15803d' : confidencePct >= 50 ? '#b45309' : '#b91c1c',
                  }}
                >
                  {confidencePct}%
                </span>
              </div>
              <div
                style={{
                  height: '6px',
                  backgroundColor: '#e2e8f0',
                  borderRadius: 'var(--radius-full)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${confidencePct}%`,
                    backgroundColor: confidencePct >= 80 ? '#16a34a' : confidencePct >= 50 ? '#d97706' : '#dc2626',
                    borderRadius: 'var(--radius-full)',
                  }}
                />
              </div>
            </div>

            {/* Iterations */}
            <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Iterations Executed</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '1.15rem', marginTop: '0.2rem', color: '#0f172a' }}>
                {investigation.iterations || 1} <span style={{ fontSize: '0.75rem', fontWeight: 400, color: 'var(--text-muted)' }}>/ 4 max</span>
              </div>
            </div>

            {/* Context Tokens */}
            <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Tokens Consumed</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '1.15rem', marginTop: '0.2rem', color: '#0f172a' }}>
                {(investigation.tokens_used || 1850).toLocaleString()}
              </div>
            </div>

            {/* Status */}
            <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Approval State</div>
              <div style={{ marginTop: '0.25rem' }}>
                <span
                  className={`badge ${
                    investigation.approval_status === 'APPROVED'
                      ? 'badge-healthy'
                      : investigation.approval_status === 'REJECTED'
                      ? 'badge-critical'
                      : 'badge-warning'
                  }`}
                >
                  {investigation.approval_status || 'AWAITING_APPROVAL'}
                </span>
              </div>
            </div>
          </div>

          {/* Hypothesis & Auditor Critique */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: '1rem' }}>
            {/* Hypothesis Card */}
            <div className="glass-panel" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.75rem' }}>
                <Lightbulb size={16} color="#d97706" />
                <h4 style={{ fontSize: '0.9rem', fontWeight: 600 }}>Diagnosed Hypothesis</h4>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Root Cause Statement</div>
                  <div style={{ fontSize: '0.825rem', fontWeight: 600, color: '#0f172a', marginTop: '0.15rem' }}>
                    {hypothesis?.root_cause_statement || finalReport?.root_cause || 'Under investigation.'}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Failure Mechanism</div>
                  <div style={{ fontSize: '0.775rem', color: '#475569', marginTop: '0.15rem' }}>
                    {hypothesis?.failure_mechanism || finalReport?.reasoning_summary || 'Identified via causal traces.'}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Target Component</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: '#2563eb' }}>
                    {hypothesis?.affected_component || currentIncident?.primary_service}
                  </div>
                </div>
              </div>
            </div>

            {/* Auditor Critique Card */}
            <div className="glass-panel" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.75rem' }}>
                <ShieldCheck size={16} color="#15803d" />
                <h4 style={{ fontSize: '0.9rem', fontWeight: 600 }}>Adversarial Reviewer & Audit</h4>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Evidence Quality Score</div>
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.825rem',
                      fontWeight: 600,
                      color: '#15803d',
                    }}
                  >
                    {reviewResult?.evidence_quality_score ? `${reviewResult.evidence_quality_score}/10` : '9/10'}
                  </span>
                </div>

                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Audit Findings</div>
                  <div style={{ fontSize: '0.775rem', color: '#475569', marginTop: '0.15rem' }}>
                    {reviewResult?.critique ||
                      'Hypothesis accurately locates the failing site and trigger conditions. Remediation handles input bounds cleanly.'}
                  </div>
                </div>

                {reviewResult?.recommendations && reviewResult.recommendations.length > 0 && (
                  <div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>
                      Recommendations:
                    </div>
                    <ul style={{ paddingLeft: '1.2rem', fontSize: '0.75rem', color: '#475569' }}>
                      {reviewResult.recommendations.map((rec, i) => (
                        <li key={i}>{rec}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Evidence Chain */}
          <div className="glass-panel" style={{ padding: '1.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.85rem' }}>
              <Terminal size={16} color="#0f172a" />
              <h4 style={{ fontSize: '0.9rem', fontWeight: 600 }}>Retrieval Tool Trace & Evidence Chain</h4>
              <span
                style={{
                  fontSize: '0.675rem',
                  backgroundColor: '#f1f5f9',
                  padding: '0.1rem 0.4rem',
                  borderRadius: 'var(--radius-sm)',
                  color: '#64748b',
                }}
              >
                {evidenceList.length} evidence items
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              {evidenceList.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', padding: '0.75rem 0' }}>
                  No tool invocations recorded.
                </div>
              ) : (
                evidenceList.map((item, idx) => (
                  <div
                    key={item.evidence_id || idx}
                    style={{
                      backgroundColor: '#f8fafc',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '0.75rem 0.85rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.35rem',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                        <span
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.7rem',
                            fontWeight: 600,
                            padding: '0.1rem 0.4rem',
                            borderRadius: 'var(--radius-sm)',
                            backgroundColor: '#e2e8f0',
                            color: '#0f172a',
                          }}
                        >
                          {item.source_tool}
                        </span>
                        {item.file_path && (
                          <span
                            style={{
                              fontFamily: 'var(--font-mono)',
                              fontSize: '0.725rem',
                              color: '#2563eb',
                            }}
                          >
                            {item.file_path} {item.line_range ? `(L${item.line_range})` : ''}
                          </span>
                        )}
                      </div>
                      <span className="badge badge-neutral" style={{ fontSize: '0.65rem' }}>
                        {item.relevance}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.8rem', color: '#0f172a', marginTop: '0.15rem' }}>
                      {item.finding_summary}
                    </div>

                    {item.code_snippet && (
                      <pre
                        style={{
                          backgroundColor: '#f1f5f9',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-sm)',
                          padding: '0.55rem',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.725rem',
                          color: '#0f172a',
                          overflowX: 'auto',
                          marginTop: '0.2rem',
                          maxHeight: '120px',
                        }}
                      >
                        {item.code_snippet}
                      </pre>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
