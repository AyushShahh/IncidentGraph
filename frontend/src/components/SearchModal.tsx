import React, { useEffect, useState } from 'react';
import { Database, FileCode, HardDrive, Layers, Radio, Search, Server, ShieldAlert, X } from 'lucide-react';
import { Incident, ServiceHealthItem } from '../types';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  incidents: Incident[];
  services: ServiceHealthItem[];
  onSelectIncident: (incident: Incident) => void;
  onSelectService: (serviceName: string) => void;
}

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  incidents,
  services,
  onSelectIncident,
  onSelectService,
}) => {
  const [query, setQuery] = useState<string>('');

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const q = query.toLowerCase().trim();

  const incidentList = Array.isArray(incidents) ? incidents : [];
  const serviceList = Array.isArray(services) ? services : [];

  const matchedServices = serviceList.filter((s) => {
    if (!q) return true;
    return s.name.toLowerCase().includes(q) || s.type.toLowerCase().includes(q);
  });

  const matchedIncidents = incidentList.filter((inc) => {
    if (!q) return true;
    const affected = Array.isArray(inc.affected_services) ? inc.affected_services : [];
    return (
      (inc.title || '').toLowerCase().includes(q) ||
      (inc.primary_service || '').toLowerCase().includes(q) ||
      (inc.severity || '').toLowerCase().includes(q) ||
      affected.some((s) => s.toLowerCase().includes(q))
    );
  });

  const getServiceIcon = (name: string) => {
    if (name.includes('postgres') || name.includes('db')) return <Database size={15} color="#2563eb" />;
    if (name.includes('redis')) return <Layers size={15} color="#dc2626" />;
    if (name.includes('kafka')) return <Radio size={15} color="#7c3aed" />;
    if (name.includes('qdrant')) return <HardDrive size={15} color="#059669" />;
    return <Server size={15} color="#475569" />;
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content"
        style={{ maxWidth: '600px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input */}
        <div
          style={{
            padding: '0.85rem 1.25rem',
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.65rem',
          }}
        >
          <Search size={16} color="var(--text-muted)" />
          <input
            autoFocus
            type="text"
            placeholder="Search services, incidents, or infrastructure..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              color: '#0f172a',
              fontSize: '0.875rem',
              outline: 'none',
            }}
          />
          <button onClick={onClose} className="btn btn-secondary btn-sm" style={{ padding: '0.25rem 0.4rem' }}>
            <X size={14} />
          </button>
        </div>

        {/* Results Body */}
        <div style={{ maxHeight: '380px', overflowY: 'auto', padding: '0.75rem' }}>
          {/* Services Group */}
          {matchedServices.length > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '0.4rem', paddingLeft: '0.5rem' }}>
                Fleet & Infrastructure ({matchedServices.length})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                {matchedServices.map((svc) => (
                  <div
                    key={svc.name}
                    onClick={() => {
                      onSelectService(svc.name);
                      onClose();
                    }}
                    style={{
                      padding: '0.5rem 0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      backgroundColor: '#ffffff',
                      border: '1px solid var(--border-subtle)',
                      transition: 'background-color 0.15s ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f8fafc')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#ffffff')}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      {getServiceIcon(svc.name)}
                      <span style={{ fontSize: '0.825rem', fontWeight: 600, color: '#0f172a', textTransform: 'capitalize' }}>
                        {svc.name}
                      </span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        ({svc.type})
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.725rem', color: '#64748b' }}>
                        {svc.latency_ms}ms
                      </span>
                      <span className={`badge ${svc.status === 'healthy' ? 'badge-healthy' : 'badge-warning'}`} style={{ fontSize: '0.65rem' }}>
                        {svc.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Incidents Group */}
          {matchedIncidents.length > 0 && (
            <div>
              <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '0.4rem', paddingLeft: '0.5rem' }}>
                Active Incidents ({matchedIncidents.length})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                {matchedIncidents.map((inc) => (
                  <div
                    key={inc.id}
                    onClick={() => {
                      onSelectIncident(inc);
                      onClose();
                    }}
                    style={{
                      padding: '0.5rem 0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      backgroundColor: '#ffffff',
                      border: '1px solid var(--border-subtle)',
                      transition: 'background-color 0.15s ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f8fafc')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#ffffff')}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <ShieldAlert size={15} color="#dc2626" />
                      <div>
                        <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#0f172a' }}>
                          {inc.title}
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                          {inc.primary_service} &bull; {inc.total_occurrences} hits
                        </div>
                      </div>
                    </div>

                    <span className={`badge ${inc.severity === 'CRITICAL' ? 'badge-critical' : 'badge-warning'}`} style={{ fontSize: '0.65rem' }}>
                      {inc.severity}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {matchedServices.length === 0 && matchedIncidents.length === 0 && (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.825rem' }}>
              No matches found for "{query}".
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
