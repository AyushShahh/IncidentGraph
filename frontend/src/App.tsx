import React, { useEffect, useState } from 'react';
import { api } from './services/api';
import { realtimeWS } from './services/websocket';
import {
  DependencyGraphData,
  FeedEvent,
  Incident,
  InvestigationDetail,
  PlatformStats,
  ServiceHealthItem,
} from './types';
import { Header } from './components/Header';
import { StatsRow } from './components/StatsRow';
import { ServicesGrid } from './components/ServicesGrid';
import { EventFeed } from './components/EventFeed';
import { IncidentQueue } from './components/IncidentQueue';
import { IncidentDetailModal } from './components/IncidentDetailModal';
import { AgentInspector } from './components/AgentInspector';
import { TopologyGraph } from './components/TopologyGraph';
import { SearchModal } from './components/SearchModal';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'topology' | 'inspector'>('dashboard');
  const [isWsConnected, setIsWsConnected] = useState<boolean>(false);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);

  // Core Platform State
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [services, setServices] = useState<ServiceHealthItem[]>([]);
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [graphData, setGraphData] = useState<DependencyGraphData | null>(null);

  // Selected Incident & Investigation Inspection State
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [investigation, setInvestigation] = useState<InvestigationDetail | null>(null);
  const [isLoadingInvestigation, setIsLoadingInvestigation] = useState<boolean>(false);

  // Load initial platform data
  const loadPlatformData = async () => {
    setIsRefreshing(true);
    try {
      const [statsRes, healthRes, eventsRes, incidentsRes, graphRes] = await Promise.allSettled([
        api.getStats(),
        api.getServiceHealth(),
        api.getRecentEvents(50),
        api.getIncidents(),
        api.getDependencyGraph(),
      ]);

      let parsedServices: ServiceHealthItem[] = [];
      if (healthRes.status === 'fulfilled') {
        const rawServices = (healthRes.value as any).services || [];
        const rawInfra = (healthRes.value as any).infrastructure || {};
        const infraItems: ServiceHealthItem[] = Object.entries(rawInfra).map(([k, v]) => ({
          name: k,
          url: '',
          type: 'infrastructure',
          status: (v as any) === 'healthy' ? 'healthy' : 'degraded',
          latency_ms: 1.0,
        }));
        parsedServices = [...rawServices.map((s: any) => ({ ...s, type: 'microservice' })), ...infraItems];
        setServices(parsedServices);
      }

      if (statsRes.status === 'fulfilled') {
        const rawStats = statsRes.value;
        const microservicesOnly = parsedServices.filter((s) => s.type === 'microservice');
        const avgLat =
          microservicesOnly.length > 0
            ? Math.round(
                (microservicesOnly.reduce((acc, s) => acc + (s.latency_ms || 0), 0) / microservicesOnly.length) * 10
              ) / 10
            : 3.5;
        const healthyCount = parsedServices.filter((s) => s.status === 'healthy').length;

        setStats({
          ...rawStats,
          auto_resolution_rate: rawStats.auto_resolve_rate_percent ?? rawStats.auto_resolution_rate ?? 0,
          avg_latency_ms: avgLat,
          total_services: parsedServices.length || 9,
          healthy_services: healthyCount || 9,
        });
      }

      if (eventsRes.status === 'fulfilled') {
        const val = eventsRes.value;
        setEvents(Array.isArray(val) ? val : (val && Array.isArray((val as any).items)) ? (val as any).items : []);
      }
      if (incidentsRes.status === 'fulfilled') {
        const val = incidentsRes.value;
        setIncidents(Array.isArray(val) ? val : (val && Array.isArray((val as any).items)) ? (val as any).items : []);
      }
      if (graphRes.status === 'fulfilled') setGraphData(graphRes.value);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Load investigation trace for selected incident
  const loadInvestigation = async (incidentId: string) => {
    setIsLoadingInvestigation(true);
    try {
      const data = await api.getInvestigation(incidentId);
      setInvestigation(data);
    } catch (err) {
      console.debug('No investigation trace found for incident:', incidentId);
      setInvestigation(null);
    } finally {
      setIsLoadingInvestigation(false);
    }
  };

  useEffect(() => {
    loadPlatformData();

    // Connect WebSocket
    realtimeWS.connect();
    const unsubConnection = realtimeWS.onConnectionChange((connected) => {
      setIsWsConnected(connected);
    });

    // Subscribe to WebSocket events
    const unsubEvents = realtimeWS.subscribe((wsMsg: any) => {
      const eventType = wsMsg.type || 'unknown';
      const eventData = wsMsg.data || {};
      const incidentId = wsMsg.incident_id || eventData.incident_id;

      // Add to live event feed
      const newEvent: FeedEvent = {
        id: `ev-${Date.now()}-${Math.random().toString(36).substr(2, 4)}`,
        type: eventType,
        timestamp: wsMsg.timestamp || new Date().toISOString(),
        service: eventData.primary_service || eventData.service,
        message: eventData.message || `${eventType} received`,
        severity: eventData.severity,
        incident_id: incidentId,
        data: eventData,
      };

      setEvents((prev) => [newEvent, ...prev.slice(0, 99)]);

      // If incident was created or updated, refresh incidents list and stats
      if (eventType.startsWith('incident:')) {
        api
          .getIncidents()
          .then((res) => setIncidents(Array.isArray(res) ? res : (res as any)?.items || []))
          .catch(console.error);
        api.getStats().then(setStats).catch(console.error);
      }

      // If agent finished or updated for currently selected incident, update its investigation
      if (selectedIncident && incidentId === selectedIncident.id) {
        loadInvestigation(selectedIncident.id);
      }
    });

    // Keyboard shortcut for search (Ctrl + K or /)
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsSearchOpen((prev) => !prev);
      } else if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault();
        setIsSearchOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);

    // Periodic poll for service health and stats (every 12s)
    const interval = setInterval(() => {
      api
        .getServiceHealth()
        .then((h: any) => {
          const rawServices = h.services || [];
          const rawInfra = h.infrastructure || {};
          const infraItems: ServiceHealthItem[] = Object.entries(rawInfra).map(([k, v]) => ({
            name: k,
            url: '',
            type: 'infrastructure',
            status: (v as any) === 'healthy' ? 'healthy' : 'degraded',
            latency_ms: 1.0,
          }));
          setServices([...rawServices.map((s: any) => ({ ...s, type: 'microservice' })), ...infraItems]);
        })
        .catch(console.debug);

      api
        .getStats()
        .then((s: any) => {
          setStats((prev) => ({
            ...(prev || {}),
            ...s,
            auto_resolution_rate: s.auto_resolve_rate_percent ?? s.auto_resolution_rate ?? prev?.auto_resolution_rate ?? 0,
          }));
        })
        .catch(console.debug);
    }, 12000);

    return () => {
      unsubConnection();
      unsubEvents();
      window.removeEventListener('keydown', handleKeyDown);
      clearInterval(interval);
    };
  }, [selectedIncident?.id]);

  // Handle selecting an incident
  const handleSelectIncident = (inc: Incident) => {
    setSelectedIncident(inc);
    loadInvestigation(inc.id);
  };

  // Handle triggering an agent run manually
  const handleTriggerAgent = async (incidentId: string, primaryService: string) => {
    try {
      await api.triggerInvestigation(incidentId, primaryService);
      loadInvestigation(incidentId);
    } catch (err: any) {
      alert(`Trigger failed: ${err.message}`);
    }
  };

  // Handle human approval
  const handleApprove = async (incidentId: string, feedback: string) => {
    await api.submitApproval(incidentId, true, feedback);
    await loadPlatformData();
    if (selectedIncident) {
      await loadInvestigation(selectedIncident.id);
    }
  };

  // Handle human rejection
  const handleReject = async (incidentId: string, feedback: string) => {
    await api.submitApproval(incidentId, false, feedback);
    await loadPlatformData();
    if (selectedIncident) {
      await loadInvestigation(selectedIncident.id);
    }
  };

  return (
    <div className="app-container">
      {/* Top Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isConnected={isWsConnected}
        onRefresh={loadPlatformData}
        onOpenSearch={() => setIsSearchOpen(true)}
        isRefreshing={isRefreshing}
      />

      {/* Main Content Area */}
      <main className="main-content">
        {activeTab === 'dashboard' && (
          <>
            {/* Top KPI Metrics */}
            <StatsRow stats={stats} services={services} isLoading={isRefreshing} />

            {/* Live Microservices Health Probing */}
            <ServicesGrid
              services={services}
              onSelectService={(svc) => {
                const matched = incidents.find((i) => i.primary_service.toLowerCase() === svc.toLowerCase());
                if (matched) handleSelectIncident(matched);
              }}
            />

            {/* Split Grid: Live Event Feed & Active Incidents Queue */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))',
                gap: '1.25rem',
              }}
            >
              <EventFeed
                events={events}
                onSelectIncident={(id) => {
                  const matched = incidents.find((i) => i.id === id);
                  if (matched) handleSelectIncident(matched);
                }}
              />

              <IncidentQueue
                incidents={incidents}
                onSelectIncident={handleSelectIncident}
                onTriggerAgent={handleTriggerAgent}
                selectedIncidentId={selectedIncident?.id}
              />
            </div>
          </>
        )}

        {activeTab === 'topology' && (
          <TopologyGraph
            graphData={graphData}
            services={services}
            selectedService={selectedIncident?.primary_service}
            onSelectService={(svc) => {
              const matched = incidents.find((i) => i.primary_service.toLowerCase() === svc.toLowerCase());
              if (matched) handleSelectIncident(matched);
            }}
            isLoading={isRefreshing}
            onReload={() => api.getDependencyGraph().then(setGraphData)}
          />
        )}

        {activeTab === 'inspector' && (
          <AgentInspector
            incidents={incidents}
            selectedIncidentId={selectedIncident?.id || incidents[0]?.id || null}
            investigation={investigation}
            isLoading={isLoadingInvestigation}
            onSelectIncident={(id) => {
              const matched = incidents.find((i) => i.id === id);
              if (matched) handleSelectIncident(matched);
              else loadInvestigation(id);
            }}
            onTriggerInvestigation={handleTriggerAgent}
          />
        )}
      </main>

      {/* Incident Detail Modal */}
      {selectedIncident && activeTab !== 'inspector' && (
        <IncidentDetailModal
          incident={selectedIncident}
          investigation={investigation}
          isLoadingInvestigation={isLoadingInvestigation}
          onClose={() => setSelectedIncident(null)}
          onApprove={handleApprove}
          onReject={handleReject}
          onViewInInspector={(id) => {
            setSelectedIncident(incidents.find((i) => i.id === id) || selectedIncident);
            setActiveTab('inspector');
          }}
        />
      )}

      {/* Global Search Modal */}
      <SearchModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        incidents={incidents}
        services={services}
        onSelectIncident={handleSelectIncident}
        onSelectService={(svc) => {
          const matched = incidents.find((i) => i.primary_service.toLowerCase() === svc.toLowerCase());
          if (matched) handleSelectIncident(matched);
        }}
      />
    </div>
  );
};

export default App;
