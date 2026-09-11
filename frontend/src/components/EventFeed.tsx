import React, { useState } from 'react';
import { AlertOctagon, Bot, Check, CheckCircle2, Clock, Terminal } from 'lucide-react';
import { FeedEvent } from '../types';

interface EventFeedProps {
  events: FeedEvent[];
  onSelectIncident?: (incidentId: string) => void;
}

export const EventFeed: React.FC<EventFeedProps> = ({ events, onSelectIncident }) => {
  const [filterType, setFilterType] = useState<string>('all');
  const eventList = Array.isArray(events) ? events : [];

  const filteredEvents = eventList.filter((ev) => {
    if (filterType === 'all') return true;
    if (filterType === 'incidents') return ev.type.includes('incident');
    if (filterType === 'agent') return ev.type.includes('agent');
    if (filterType === 'logs') return ev.type.includes('log');
    return true;
  });

  const formatShortTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return isoString;
    }
  };

  const getEventBadge = (type: string) => {
    if (type === 'incident:created' || type === 'incident_created') {
      return (
        <span className="badge badge-critical">
          <AlertOctagon size={11} /> Incident Created
        </span>
      );
    }
    if (type === 'agent:started' || type === 'agent_started') {
      return (
        <span className="badge badge-info">
          <Bot size={11} /> Investigation Started
        </span>
      );
    }
    if (type === 'agent:step') {
      return (
        <span className="badge badge-neutral">
          <Terminal size={11} /> Agent Step
        </span>
      );
    }
    if (type === 'agent:hypothesis') {
      return (
        <span className="badge badge-warning">
          Hypothesis
        </span>
      );
    }
    if (type === 'agent:fix_ready' || type === 'agent_fix_ready') {
      return (
        <span className="badge badge-warning" style={{ background: '#fef3c7', color: '#92400e' }}>
          <CheckCircle2 size={11} /> Fix Ready
        </span>
      );
    }
    if (type === 'agent:approved') {
      return (
        <span className="badge badge-healthy">
          <Check size={11} /> Approved
        </span>
      );
    }
    return (
      <span className="badge badge-neutral">
        <Terminal size={11} /> Log Telemetry
      </span>
    );
  };

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
          <Terminal size={16} color="#0f172a" />
          <h3 style={{ fontSize: '0.925rem', fontWeight: 600 }}>Live Telemetry & Event Feed</h3>
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
            {filteredEvents.length} events
          </span>
        </div>

        {/* Filter Pills */}
        <div style={{ display: 'flex', gap: '0.25rem' }}>
          {['all', 'incidents', 'agent', 'logs'].map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterType(cat)}
              style={{
                fontSize: '0.725rem',
                textTransform: 'capitalize',
                padding: '0.2rem 0.55rem',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                background: filterType === cat ? '#0f172a' : '#ffffff',
                color: filterType === cat ? '#ffffff' : '#64748b',
                cursor: 'pointer',
                fontWeight: 500,
              }}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          maxHeight: '400px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          paddingRight: '0.25rem',
        }}
      >
        {filteredEvents.length === 0 ? (
          <div
            style={{
              padding: '2.5rem 1rem',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.825rem',
            }}
          >
            Awaiting streaming service log events and agent telemetry...
          </div>
        ) : (
          filteredEvents.map((ev) => (
            <div
              key={ev.id}
              onClick={() => ev.incident_id && onSelectIncident && onSelectIncident(ev.incident_id)}
              style={{
                backgroundColor: '#f8fafc',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '0.65rem 0.85rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.3rem',
                cursor: ev.incident_id ? 'pointer' : 'default',
                transition: 'border-color 0.15s ease, background-color 0.15s ease',
              }}
              onMouseEnter={(e) => {
                if (ev.incident_id) {
                  e.currentTarget.style.borderColor = '#94a3b8';
                  e.currentTarget.style.backgroundColor = '#f1f5f9';
                }
              }}
              onMouseLeave={(e) => {
                if (ev.incident_id) {
                  e.currentTarget.style.borderColor = 'var(--border-subtle)';
                  e.currentTarget.style.backgroundColor = '#f8fafc';
                }
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                  {getEventBadge(ev.type)}
                  {ev.service && (
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.725rem',
                        color: '#0f172a',
                        fontWeight: 600,
                      }}
                    >
                      {ev.service}
                    </span>
                  )}
                </div>

                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.25rem',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.7rem',
                    color: 'var(--text-muted)',
                  }}
                >
                  <Clock size={11} />
                  {formatShortTime(ev.timestamp)}
                </span>
              </div>

              <div
                style={{
                  fontSize: '0.8rem',
                  color: '#334155',
                  lineHeight: 1.4,
                  wordBreak: 'break-word',
                }}
              >
                {ev.message}
              </div>

              {ev.incident_id && (
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.1rem' }}>
                  <span style={{ fontSize: '0.7rem', color: '#2563eb', fontWeight: 500 }}>
                    Inspect Investigation &rarr;
                  </span>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
