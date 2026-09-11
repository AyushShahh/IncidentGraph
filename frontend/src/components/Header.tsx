import React, { useEffect, useState } from 'react';
import { Activity, Cpu, Network, RefreshCw, Search, Shield, Wifi, WifiOff } from 'lucide-react';

interface HeaderProps {
  activeTab: 'dashboard' | 'topology' | 'inspector';
  setActiveTab: (tab: 'dashboard' | 'topology' | 'inspector') => void;
  isConnected: boolean;
  onRefresh: () => void;
  onOpenSearch: () => void;
  isRefreshing?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  isConnected,
  onRefresh,
  onOpenSearch,
  isRefreshing = false,
}) => {
  const [time, setTime] = useState<string>('');

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        backgroundColor: '#ffffff',
        borderBottom: '1px solid var(--border-subtle)',
        padding: '0.75rem 2rem',
      }}
    >
      <div
        style={{
          maxWidth: '1440px',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        {/* Brand & Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            style={{
              width: '34px',
              height: '34px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: '#0f172a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Shield size={18} color="#ffffff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '1.05rem', fontWeight: 600, color: '#0f172a', letterSpacing: '-0.02em' }}>
                IncidentGraph
              </span>
              <span
                style={{
                  fontSize: '0.65rem',
                  fontWeight: 600,
                  padding: '0.1rem 0.4rem',
                  borderRadius: 'var(--radius-sm)',
                  background: '#f1f5f9',
                  color: '#475569',
                  border: '1px solid #e2e8f0',
                  textTransform: 'uppercase',
                }}
              >
                Ops v1.0
              </span>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Autonomous RCA & Incident Resolution
            </div>
          </div>
        </div>

        {/* Navigation Tabs - Minimalist Segmented Control */}
        <nav
          style={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: '#f1f5f9',
            padding: '0.2rem',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <button
            onClick={() => setActiveTab('dashboard')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.4rem 0.85rem',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: activeTab === 'dashboard' ? '#ffffff' : 'transparent',
              color: activeTab === 'dashboard' ? '#0f172a' : '#64748b',
              boxShadow: activeTab === 'dashboard' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
              fontSize: '0.8rem',
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <Activity size={14} />
            Dashboard
          </button>
          <button
            onClick={() => setActiveTab('topology')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.4rem 0.85rem',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: activeTab === 'topology' ? '#ffffff' : 'transparent',
              color: activeTab === 'topology' ? '#0f172a' : '#64748b',
              boxShadow: activeTab === 'topology' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
              fontSize: '0.8rem',
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <Network size={14} />
            Dependency Graph
          </button>
          <button
            onClick={() => setActiveTab('inspector')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.4rem 0.85rem',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: activeTab === 'inspector' ? '#ffffff' : 'transparent',
              color: activeTab === 'inspector' ? '#0f172a' : '#64748b',
              boxShadow: activeTab === 'inspector' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
              fontSize: '0.8rem',
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <Cpu size={14} />
            Agent Inspector
          </button>
        </nav>

        {/* Search, Refresh & Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          {/* Global Search Button */}
          <button
            onClick={onOpenSearch}
            className="btn btn-secondary btn-sm"
            style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', color: '#475569' }}
            title="Search incidents, services, symbols (Ctrl+K)"
          >
            <Search size={14} />
            <span>Search...</span>
            <kbd
              style={{
                fontSize: '0.65rem',
                backgroundColor: '#f1f5f9',
                padding: '0.1rem 0.35rem',
                borderRadius: '3px',
                border: '1px solid #cbd5e1',
                color: '#64748b',
              }}
            >
              Ctrl+K
            </kbd>
          </button>

          {/* Refresh Button */}
          <button
            onClick={onRefresh}
            className="btn btn-secondary btn-sm"
            disabled={isRefreshing}
            title="Refresh metrics"
          >
            <RefreshCw size={13} className={isRefreshing ? 'spin-anim' : ''} />
          </button>

          {/* WebSocket Status Indicator */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.3rem 0.6rem',
              borderRadius: 'var(--radius-sm)',
              background: isConnected ? '#f0fdf4' : '#fef2f2',
              border: `1px solid ${isConnected ? '#bbf7d0' : '#fecaca'}`,
              fontSize: '0.725rem',
              fontWeight: 500,
              color: isConnected ? '#15803d' : '#b91c1c',
            }}
          >
            <span className={`pulse-dot ${isConnected ? 'healthy' : 'critical'}`} />
            <span>{isConnected ? 'LIVE' : 'OFFLINE'}</span>
          </div>

          {/* Clock */}
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.75rem',
              color: '#64748b',
              padding: '0.3rem 0.55rem',
              borderRadius: 'var(--radius-sm)',
              background: '#f8fafc',
              border: '1px solid var(--border-subtle)',
            }}
          >
            {time}
          </div>
        </div>
      </div>
    </header>
  );
};
