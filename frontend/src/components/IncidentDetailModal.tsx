import React, { useState } from 'react';
import {
  Code2,
  ExternalLink,
  FileCode,
  Layers,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
  X,
  Zap,
} from 'lucide-react';
import { Incident, InvestigationDetail } from '../types';

interface IncidentDetailModalProps {
  incident: Incident;
  investigation: InvestigationDetail | null;
  isLoadingInvestigation: boolean;
  onClose: () => void;
  onApprove: (incidentId: string, feedback: string) => Promise<void>;
  onReject: (incidentId: string, feedback: string) => Promise<void>;
  onViewInInspector: (incidentId: string) => void;
}

export const IncidentDetailModal: React.FC<IncidentDetailModalProps> = ({
  incident,
  investigation,
  isLoadingInvestigation,
  onClose,
  onApprove,
  onReject,
  onViewInInspector,
}) => {
  const [feedback, setFeedback] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const finalReport = investigation?.final_report;
  const hypothesis = investigation?.hypothesis;
  const confidence = investigation?.confidence || finalReport?.confidence || 0.0;
  const confidencePct = Math.round(confidence * 100);

  const handleApprove = async () => {
    setIsSubmitting(true);
    try {
      await onApprove(incident.id, feedback);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    setIsSubmitting(true);
    try {
      await onReject(incident.id, feedback);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div
          style={{
            padding: '1rem 1.5rem',
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            backgroundColor: '#ffffff',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: '#fef2f2',
                border: '1px solid #fecaca',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <ShieldAlert size={16} color="#dc2626" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '1rem', fontWeight: 600, color: '#0f172a' }}>
                  Incident Details & Root Cause Analysis
                </span>
                <span className={`badge ${incident.severity === 'CRITICAL' ? 'badge-critical' : 'badge-warning'}`}>
                  {incident.severity}
                </span>
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.725rem', color: 'var(--text-muted)' }}>
                ID: {incident.id}
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="btn btn-secondary btn-sm"
            style={{ padding: '0.3rem', borderRadius: 'var(--radius-sm)' }}
          >
            <X size={15} />
          </button>
        </div>

        {/* Modal Body */}
        <div style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* Quick Metrics Bar */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
              gap: '0.75rem',
              backgroundColor: '#f8fafc',
              padding: '0.75rem 1rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Primary Service</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#0f172a' }}>
                {incident.primary_service}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Total Hits</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#0f172a' }}>
                {incident.total_occurrences}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Confidence</div>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 600,
                  color: confidencePct >= 80 ? '#15803d' : confidencePct >= 50 ? '#b45309' : '#b91c1c',
                }}
              >
                {isLoadingInvestigation ? 'Computing...' : `${confidencePct}%`}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Status</div>
              <div style={{ fontWeight: 600, fontSize: '0.8rem', color: '#0f172a' }}>
                {investigation?.approval_status || incident.status}
              </div>
            </div>
          </div>

          {/* Root Cause Card */}
          <div
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.85rem 1rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.35rem' }}>
              <Zap size={15} color="#d97706" />
              <h4 style={{ fontSize: '0.875rem', fontWeight: 600 }}>Diagnosed Root Cause</h4>
            </div>
            <p style={{ fontSize: '0.825rem', color: '#334155', lineHeight: 1.45 }}>
              {finalReport?.root_cause || hypothesis?.root_cause_statement || incident.title}
            </p>
          </div>

          {/* Suggested Fix / Patch */}
          <div
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.85rem 1rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.45rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <Code2 size={15} color="#15803d" />
                <h4 style={{ fontSize: '0.875rem', fontWeight: 600 }}>Recommended Fix & Patch</h4>
              </div>
              <button
                onClick={() => onViewInInspector(incident.id)}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: '0.725rem' }}
              >
                <ExternalLink size={11} />
                Open Inspector
              </button>
            </div>

            <pre
              style={{
                backgroundColor: '#f8fafc',
                padding: '0.75rem',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                fontSize: '0.775rem',
                color: '#0f172a',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: '160px',
                overflowY: 'auto',
              }}
            >
              {finalReport?.suggested_fix || 'Investigation underway. Agent synthesizing verified patch...'}
            </pre>
          </div>

          {/* Blast Radius & Affected Scope */}
          <div
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.85rem 1rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.45rem' }}>
              <Layers size={15} color="#475569" />
              <h4 style={{ fontSize: '0.875rem', fontWeight: 600 }}>Blast Radius & Affected Services</h4>
            </div>
            <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
              {(Array.isArray(incident.affected_services) ? incident.affected_services : []).map((svc) => (
                <div
                  key={svc}
                  style={{
                    backgroundColor: '#f1f5f9',
                    border: '1px solid var(--border-subtle)',
                    padding: '0.2rem 0.55rem',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.725rem',
                    color: '#0f172a',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {svc}
                </div>
              ))}
            </div>
          </div>

          {/* Inspected Files */}
          {finalReport?.inspected_files && Array.isArray(finalReport.inspected_files) && finalReport.inspected_files.length > 0 && (
            <div>
              <div style={{ fontSize: '0.725rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                Files Inspected by Agent:
              </div>
              <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                {finalReport.inspected_files.map((f) => (
                  <span
                    key={f}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.7rem',
                      backgroundColor: '#f1f5f9',
                      padding: '0.15rem 0.45rem',
                      borderRadius: '3px',
                      color: '#0f172a',
                    }}
                  >
                    <FileCode size={11} color="#64748b" />
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Human Decision Review */}
          <div
            style={{
              marginTop: '0.25rem',
              padding: '0.85rem 1rem',
              backgroundColor: '#f8fafc',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.65rem',
            }}
          >
            <h4 style={{ fontSize: '0.825rem', fontWeight: 600 }}>Human-in-the-Loop Review</h4>
            <input
              type="text"
              placeholder="Add optional reviewer feedback..."
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              style={{
                width: '100%',
                backgroundColor: '#ffffff',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '0.45rem 0.7rem',
                color: '#0f172a',
                fontSize: '0.8rem',
                outline: 'none',
              }}
            />

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <button
                onClick={handleReject}
                disabled={isSubmitting}
                className="btn btn-danger btn-sm"
              >
                <ThumbsDown size={13} />
                Reject Fix
              </button>
              <button
                onClick={handleApprove}
                disabled={isSubmitting}
                className="btn btn-success btn-sm"
              >
                <ThumbsUp size={13} />
                Approve & Commit to Memory
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
