import React, { useEffect, useRef, useState } from 'react';
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
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  const selectedIncidentRef = useRef<Incident | null>(null);
  useEffect(() => {
    selectedIncidentRef.current = selectedIncident;
  }, [selectedIncident]);

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
        const list = Array.isArray(val) ? val : (val && Array.isArray((val as any).items)) ? (val as any).items : [];
        setIncidents(list);
        if (!selectedIncidentRef.current && list.length > 0) {
          setSelectedIncident(list[0]);
          selectedIncidentRef.current = list[0];
          loadInvestigation(list[0].id, true /* silent */);
        }
      }
      if (graphRes.status === 'fulfilled') setGraphData(graphRes.value);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Load investigation trace for selected incident
  const loadInvestigation = async (incidentId: string, silent: boolean = false) => {
    if (!silent) {
      setIsLoadingInvestigation(true);
    }
    try {
      const data = await api.getInvestigation(incidentId);
      setInvestigation((prev) => {
        if (!prev && !data) return null;
        if (JSON.stringify(prev) === JSON.stringify(data)) return prev;
        return data;
      });
    } catch (err) {
      console.debug('No investigation trace found for incident:', incidentId);
      if (!silent) {
        setInvestigation(null);
      }
    } finally {
      if (!silent) {
        setIsLoadingInvestigation(false);
      }
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

      if (eventType === 'init') {
        if (Array.isArray(eventData.history) && eventData.history.length > 0) {
          setEvents((prev) => (prev.length === 0 ? eventData.history : prev));
        }
        return;
      }
      if (eventType === 'pong') return;

      // Add to live event feed
      const newEvent: FeedEvent = {
        id: wsMsg.id || `ev-${Date.now()}-${Math.random().toString(36).substr(2, 4)}`,
        type: eventType,
        timestamp: wsMsg.timestamp || new Date().toISOString(),
        service: wsMsg.service || eventData.primary_service || eventData.service,
        message: wsMsg.message || eventData.message || `${eventType} received`,
        severity: wsMsg.severity || eventData.severity,
        incident_id: incidentId,
        data: eventData,
      };

      setEvents((prev) => {
        const withoutDup = prev.filter((e) => e.id !== newEvent.id);
        return [newEvent, ...withoutDup.slice(0, 99)];
      });

      // If incident was created, updated, or agent step/fix occurred, refresh incidents list and stats
      if (eventType.startsWith('incident:') || eventType.startsWith('agent:')) {
        api
          .getIncidents()
          .then((res) => {
            const list = Array.isArray(res) ? res : (res as any)?.items || [];
            setIncidents(list);
            if (!selectedIncidentRef.current && list.length > 0) {
              setSelectedIncident(list[0]);
              selectedIncidentRef.current = list[0];
              loadInvestigation(list[0].id, true /* silent */);
            } else if (selectedIncidentRef.current) {
              const updatedCurrent = list.find((i: any) => i.id === selectedIncidentRef.current?.id);
              if (
                updatedCurrent &&
                (updatedCurrent.status !== selectedIncidentRef.current.status ||
                  updatedCurrent.total_occurrences !== selectedIncidentRef.current.total_occurrences ||
                  Boolean(updatedCurrent.resolution) !== Boolean(selectedIncidentRef.current.resolution))
              ) {
                setSelectedIncident(updatedCurrent);
                selectedIncidentRef.current = updatedCurrent;
              }
            }
          })
          .catch(console.error);

        api.getStats().then((s: any) => {
          setStats((prev) => ({
            ...(prev || {}),
            ...s,
            auto_resolution_rate: s.auto_resolve_rate_percent ?? s.auto_resolution_rate ?? prev?.auto_resolution_rate ?? 0,
          }));
        }).catch(console.error);
      }

      // If agent finished or updated for currently selected incident, update its investigation trace silently
      if (selectedIncidentRef.current && (incidentId === selectedIncidentRef.current.id || !incidentId)) {
        loadInvestigation(selectedIncidentRef.current.id, true /* silent */);
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

    // Periodic poll for service health, stats, and incidents (every 5s)
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
          const combined = [...rawServices.map((s: any) => ({ ...s, type: 'microservice' })), ...infraItems];
          setServices((prev) => (JSON.stringify(prev) === JSON.stringify(combined) ? prev : combined));
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

      api
        .getIncidents()
        .then((res) => {
          const list = Array.isArray(res) ? res : (res as any)?.items || [];
          setIncidents((prev) => {
            const hasChanged =
              prev.length !== list.length ||
              prev.some(
                (p, i) =>
                  p.id !== list[i]?.id ||
                  p.status !== list[i]?.status ||
                  p.total_occurrences !== list[i]?.total_occurrences ||
                  Boolean(p.resolution) !== Boolean(list[i]?.resolution)
              );
            if (!hasChanged) return prev;
            return list;
          });
          if (!selectedIncidentRef.current && list.length > 0) {
            setSelectedIncident(list[0]);
            selectedIncidentRef.current = list[0];
            loadInvestigation(list[0].id, true /* silent */);
          } else if (selectedIncidentRef.current) {
            const updatedCurrent = list.find((i: any) => i.id === selectedIncidentRef.current?.id);
            if (
              updatedCurrent &&
              (updatedCurrent.status !== selectedIncidentRef.current.status ||
                updatedCurrent.total_occurrences !== selectedIncidentRef.current.total_occurrences ||
                Boolean(updatedCurrent.resolution) !== Boolean(selectedIncidentRef.current.resolution))
            ) {
              setSelectedIncident(updatedCurrent);
              selectedIncidentRef.current = updatedCurrent;
            }
          }
        })
        .catch(console.debug);

      api
        .getRecentEvents(50)
        .then((evList) => {
          if (Array.isArray(evList) && evList.length > 0) {
            setEvents((prev) => {
              if (prev.length === 0) return evList;
              const existingIds = new Set(prev.map((e) => e.id));
              const novel = evList.filter((e) => !existingIds.has(e.id));
              if (novel.length > 0) {
                return [...novel, ...prev].slice(0, 100);
              }
              return prev;
            });
          }
        })
        .catch(console.debug);

      if (selectedIncidentRef.current) {
        loadInvestigation(selectedIncidentRef.current.id, true /* silent */);
      }
    }, 5000);

    return () => {
      unsubConnection();
      unsubEvents();
      window.removeEventListener('keydown', handleKeyDown);
      clearInterval(interval);
    };
  }, []);

  // Handle selecting an incident
  const handleSelectIncident = (inc: Incident, openModal: boolean = false) => {
    const isDifferent = selectedIncident?.id !== inc.id;
    setSelectedIncident(inc);
    selectedIncidentRef.current = inc;
    if (openModal) {
      setIsModalOpen(true);
    }
    if (isDifferent) {
      setInvestigation(null);
      loadInvestigation(inc.id, false /* show initial loader */);
    } else {
      loadInvestigation(inc.id, true /* silent in-place refresh */);
    }
  };

  // Handle triggering an agent run manually
  const handleTriggerAgent = async (incidentId: string, primaryService: string) => {
    try {
      await api.triggerInvestigation(incidentId, primaryService);
      loadInvestigation(incidentId, true /* silent */);
    } catch (err: any) {
      console.error('Failed to trigger agent investigation:', err);
      alert(`Trigger failed: ${err.message || err}`);
    }
  };

  // Handle human approval
  const handleApprove = async (incidentId: string, feedback: string) => {
    await api.submitApproval(incidentId, true, feedback);
    setIsModalOpen(false);
    await loadPlatformData();
    if (selectedIncident) {
      await loadInvestigation(selectedIncident.id, true);
    }
  };

  // Handle human rejection
  const handleReject = async (incidentId: string, feedback: string) => {
    await api.submitApproval(incidentId, false, feedback);
    setIsModalOpen(false);
    await loadPlatformData();
    if (selectedIncident) {
      await loadInvestigation(selectedIncident.id, true);
    }
  };

  return (
    <div className="app-container">
      {/* Top Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isConnected={isWsConnected}
        isRefreshing={isRefreshing}
        onRefresh={loadPlatformData}
        onOpenSearch={() => setIsSearchOpen(true)}
      />

      {/* Main Content Area */}
      <main className="main-content">
        {activeTab === 'dashboard' && (
          <>
            {/* Top Stats Overview */}
            <StatsRow stats={stats} services={services} isLoading={isRefreshing} />

            {/* Live Microservices & Infrastructure Fleet Grid */}
            <ServicesGrid
              services={services}
              onSelectService={(svc) => {
                const matched = incidents.find((i) => i.primary_service.toLowerCase() === svc.toLowerCase());
                if (matched) handleSelectIncident(matched, true);
              }}
            />

            {/* Two Column Grid: Event Feed & Active Incidents */}
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
                  if (matched) handleSelectIncident(matched, true);
                }}
              />

              <IncidentQueue
                incidents={incidents}
                onSelectIncident={(inc) => handleSelectIncident(inc, true)}
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
              if (matched) handleSelectIncident(matched, true);
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
              if (matched) handleSelectIncident(matched, false);
              else loadInvestigation(id);
            }}
            onTriggerInvestigation={handleTriggerAgent}
          />
        )}
      </main>

      {/* Incident Detail Modal */}
      {selectedIncident && isModalOpen && activeTab !== 'inspector' && (
        <IncidentDetailModal
          incident={selectedIncident}
          investigation={investigation}
          isLoadingInvestigation={isLoadingInvestigation}
          onClose={() => setIsModalOpen(false)}
          onApprove={handleApprove}
          onReject={handleReject}
          onViewInInspector={(id) => {
            setIsModalOpen(false);
            const matched = incidents.find((i) => i.id === id) || selectedIncident;
            setSelectedIncident(matched);
            selectedIncidentRef.current = matched;
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
        onSelectIncident={(inc) => {
          handleSelectIncident(inc, true);
          setIsSearchOpen(false);
        }}
        onSelectService={(svc) => {
          const matched = incidents.find((i) => i.primary_service.toLowerCase() === svc.toLowerCase());
          if (matched) {
            handleSelectIncident(matched, true);
            setIsSearchOpen(false);
          }
        }}
      />
    </div>
  );
};

export default App;
