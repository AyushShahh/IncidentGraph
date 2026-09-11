import React from 'react';
import { AlertCircle, CheckCircle, CheckCheck, Clock, Eye, Play, RotateCw, ShieldAlert } from 'lucide-react';
import { Incident } from '../types';

interface IncidentQueueProps {
  incidents: Incident[];
  onSelectIncident: (incident: Incident) => void;
  onTriggerAgent: (incidentId: string, primaryService: string) => void;
  selectedIncidentId?: string | null;
}

export const IncidentQueue: React.FC<IncidentQueueProps> = ({
  incidents,
  onSelectIncident,
  onTriggerAgent,
  selectedIncidentId,
}) => {
  const getSeverityBadge = (severity: string) => {
    const s = (severity || 'MEDIUM').toUpperCase();
    if (s === 'CRITICAL') return <span className="badge badge-critical">CRITICAL</span>;
    if (s === 'HIGH') return <span className="badge badge-warning">HIGH</span>;
    if (s === 'MEDIUM') return <span className="badge badge-info">MEDIUM</span>;
    return <span className="badge badge-neutral">LOW</span>;
  };

  const getStatusBadge = (status: string) => {
    if (status === 'RESOLVED') {
      return (
        <span className="badge badge-healthy">
          <CheckCircle size={11} /> Resolved
        </span>
      );
    }
    if (status === 'AWAITING_APPROVAL') {
      return (
        <span className="badge badge-warning">
          <Clock size={11} /> Awaiting Approval
        </span>
      );
    }
    if (status === 'INVESTIGATING') {
      return (
        <span className="badge badge-info">
          <RotateCw size={11} className="spin-slow" /> Investigating
        </span>
      );
    }
    if (status === 'ACTIVE') {
      return (
        <span className="badge badge-critical">
          <AlertCircle size={11} /> Active
        </span>
      );
    }
    return <span className="badge badge-neutral">{status}</span>;
  };

  const formatRelativeTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  };

  const incidentList = Array.isArray(incidents) ? incidents : [];

  return (
    <div className="glass-panel" style={{ padding: '1.25rem', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '1rem',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ShieldAlert size={16} color="#dc2626" />
          <h3 style={{ fontSize: '0.925rem', fontWeight: 600 }}>Active & Clustered Incidents</h3>
          <span
            style={{
              fontSize: '0.7rem',
              backgroundColor: '#f1f5f9',
              padding: '0.1rem 0.45rem',
              borderRadius: 'var(--radius-sm)',
              color: '#64748b',
              fontWeight: 500,
            }}
          >
            {incidentList.length} total
          </span>
        </div>

        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          Causal Log Fingerprint Deduplication
        </span>
      </div>

      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          maxHeight: '400px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.65rem',
          paddingRight: '0.25rem',
        }}
      >
        {incidentList.length === 0 ? (
          <div
            style={{
              padding: '2.5rem 1rem',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.825rem',
            }}
          >
            No active incidents detected. All microservices operating nominally.
          </div>
        ) : (
          incidentList.map((inc) => {
            const isSelected = selectedIncidentId === inc.id;

            return (
              <div
                key={inc.id}
                onClick={() => onSelectIncident(inc)}
                style={{
                  backgroundColor: isSelected ? '#eff6ff' : '#f8fafc',
                  border: `1px solid ${isSelected ? '#3b82f6' : 'var(--border-subtle)'}`,
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.85rem 1rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.45rem',
                  cursor: 'pointer',
                  transition: 'border-color 0.15s ease, background-color 0.15s ease',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.borderColor = '#cbd5e1';
                    e.currentTarget.style.backgroundColor = '#f1f5f9';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.borderColor = 'var(--border-subtle)';
                    e.currentTarget.style.backgroundColor = '#f8fafc';
                  }
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                    {getSeverityBadge(inc.severity)}
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.725rem',
                        fontWeight: 600,
                        color: '#0f172a',
                        background: '#e2e8f0',
                        padding: '0.1rem 0.45rem',
                        borderRadius: 'var(--radius-sm)',
                      }}
                    >
                      {inc.primary_service}
                    </span>
                    {getStatusBadge(inc.status)}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.725rem',
                        color: 'var(--text-muted)',
                      }}
                    >
                      {inc.total_occurrences} {inc.total_occurrences === 1 ? 'hit' : 'hits'}
                    </span>
                    <span
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.2rem',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.7rem',
                        color: 'var(--text-muted)',
                      }}
                    >
                      <Clock size={11} />
                      {formatRelativeTime(inc.last_seen)}
                    </span>
                  </div>
                </div>

                <div
                  style={{
                    fontSize: '0.825rem',
                    fontWeight: 600,
                    color: '#0f172a',
                    lineHeight: 1.35,
                  }}
                >
                  {inc.title}
                </div>

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '0.5rem',
                    marginTop: '0.2rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Affected:</span>
                    {(Array.isArray(inc.affected_services) ? inc.affected_services : []).map((svc) => (
                      <span
                        key={svc}
                        style={{
                          fontSize: '0.675rem',
                          color: '#475569',
                          backgroundColor: '#ffffff',
                          border: '1px solid #e2e8f0',
                          padding: '0.1rem 0.35rem',
                          borderRadius: '3px',
                        }}
                      >
                        {svc}
                      </span>
                    ))}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    {inc.status === 'INVESTIGATING' ? (
                      <>
                        <span
                          className="badge badge-info"
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.25rem',
                            fontSize: '0.72rem',
                            padding: '0.2rem 0.5rem',
                          }}
                        >
                          <RotateCw size={11} className="spin-slow" />
                          Investigating...
                        </span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectIncident(inc);
                          }}
                          className="btn btn-secondary btn-sm"
                          style={{ fontSize: '0.725rem', padding: '0.2rem 0.5rem' }}
                        >
                          <Eye size={11} />
                          Live Trace
                        </button>
                      </>
                    ) : inc.status === 'AWAITING_APPROVAL' ? (
                      <>
                        <span
                          className="badge badge-warning"
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.25rem',
                            fontSize: '0.72rem',
                            padding: '0.2rem 0.5rem',
                          }}
                        >
                          <Clock size={11} />
                          Fix Ready
                        </span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectIncident(inc);
                          }}
                          className="btn btn-primary btn-sm"
                          style={{ fontSize: '0.725rem', padding: '0.2rem 0.6rem' }}
                        >
                          <Eye size={11} />
                          Review & Approve
                        </button>
                      </>
                    ) : (inc.status === 'RESOLVED' || Boolean(inc.resolution)) ? (
                      <>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onTriggerAgent(inc.id, inc.primary_service);
                          }}
                          className="btn btn-ghost btn-sm"
                          style={{ fontSize: '0.725rem', padding: '0.2rem 0.45rem', color: '#64748b' }}
                          title="Re-run autonomous investigation"
                        >
                          <RotateCw size={11} />
                          Re-run
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectIncident(inc);
                          }}
                          className="btn btn-primary btn-sm"
                          style={{ fontSize: '0.725rem', padding: '0.2rem 0.6rem' }}
                        >
                          <Eye size={11} />
                          View RCA
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onTriggerAgent(inc.id, inc.primary_service);
                          }}
                          className="btn btn-secondary btn-sm"
                          style={{ fontSize: '0.725rem', padding: '0.2rem 0.55rem' }}
                          title="Run Autonomous Agent"
                        >
                          <Play size={11} />
                          Investigate
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectIncident(inc);
                          }}
                          className="btn btn-secondary btn-sm"
                          style={{ fontSize: '0.725rem', padding: '0.2rem 0.55rem' }}
                        >
                          <Eye size={11} />
                          Inspect
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
