import React from 'react';
import { Database, HardDrive, Server, Radio, Layers } from 'lucide-react';
import { ServiceHealthItem } from '../types';

interface ServicesGridProps {
  services: ServiceHealthItem[];
  onSelectService?: (serviceName: string) => void;
}

export const ServicesGrid: React.FC<ServicesGridProps> = ({ services, onSelectService }) => {
  const serviceList = Array.isArray(services) ? services : [];

  const getIcon = (type: string, name: string) => {
    if (name.includes('postgres') || name.includes('db')) return <Database size={15} color="#2563eb" />;
    if (name.includes('redis')) return <Layers size={15} color="#dc2626" />;
    if (name.includes('kafka')) return <Radio size={15} color="#7c3aed" />;
    if (name.includes('qdrant')) return <HardDrive size={15} color="#059669" />;
    return <Server size={15} color="#475569" />;
  };

  return (
    <div className="glass-panel" style={{ padding: '1.25rem' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Server size={16} color="#0f172a" />
          <h3 style={{ fontSize: '0.925rem', fontWeight: 600 }}>Fleet & Infrastructure Mesh</h3>
        </div>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          Active Probing & Latency Telemetry
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
          gap: '0.75rem',
        }}
      >
        {serviceList.map((svc) => {
          const isHealthy = svc.status === 'healthy';
          const isDegraded = svc.status === 'degraded';
          const statusClass = isHealthy ? 'healthy' : isDegraded ? 'warning' : 'critical';

          return (
            <div
              key={svc.name}
              onClick={() => onSelectService && onSelectService(svc.name)}
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '0.75rem 0.85rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.45rem',
                cursor: 'pointer',
                transition: 'border-color 0.15s ease, transform 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-hover)';
                e.currentTarget.style.transform = 'translateY(-1px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-subtle)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                  {getIcon(svc.type, svc.name)}
                  <span style={{ fontWeight: 600, fontSize: '0.825rem', color: '#0f172a', textTransform: 'capitalize' }}>
                    {svc.name}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <span className={`pulse-dot ${statusClass}`} />
                  <span
                    style={{
                      fontSize: '0.675rem',
                      fontWeight: 600,
                      color: isHealthy ? '#15803d' : isDegraded ? '#b45309' : '#b91c1c',
                      textTransform: 'uppercase',
                    }}
                  >
                    {svc.status}
                  </span>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '0.15rem' }}>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  {svc.type === 'microservice' ? 'HTTP Probe' : 'Driver Ping'}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.75rem',
                    color: svc.latency_ms < 50 ? '#15803d' : svc.latency_ms < 200 ? '#b45309' : '#b91c1c',
                    fontWeight: 500,
                  }}
                >
                  {svc.latency_ms} ms
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
