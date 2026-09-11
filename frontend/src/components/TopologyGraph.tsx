import React, { useEffect, useRef, useState } from 'react';
import cytoscape, { Core } from 'cytoscape';
import { AlertTriangle, Maximize2, Network, RefreshCw, ZoomIn, ZoomOut } from 'lucide-react';
import { DependencyGraphData, ServiceHealthItem } from '../types';

interface TopologyGraphProps {
  graphData: DependencyGraphData | null;
  services: ServiceHealthItem[];
  selectedService?: string | null;
  onSelectService?: (serviceName: string) => void;
  isLoading?: boolean;
  onReload?: () => void;
}

export const TopologyGraph: React.FC<TopologyGraphProps> = ({
  graphData,
  services,
  selectedService,
  onSelectService,
  isLoading = false,
  onReload,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [selectedNodeInfo, setSelectedNodeInfo] = useState<any | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    try {
      setRenderError(null);
      const elements: any[] = [];
      const nodeIds = new Set<string>();

      const rawNodes = (graphData && Array.isArray(graphData.nodes)) ? graphData.nodes : [];
      const rawEdges = (graphData && Array.isArray(graphData.edges)) ? graphData.edges : [];

      if (rawNodes.length > 0) {
        rawNodes.forEach((node, idx) => {
          const serviceName = String((node as any).service_name || node.id || node.label || `node-${idx}`).toLowerCase();
          nodeIds.add(serviceName);

          const svcHealth = (Array.isArray(services) ? services : []).find(
            (s) => s.name.toLowerCase() === serviceName
          );
          const isHealthy = svcHealth?.status === 'healthy';
          const isSelected = selectedService?.toLowerCase() === serviceName;

          elements.push({
            data: {
              id: serviceName,
              label: serviceName.toUpperCase(),
              type: node.type || 'service',
              status: svcHealth?.status || 'healthy',
              latency: svcHealth?.latency_ms || 3,
              isSelected,
            },
          });
        });

        rawEdges.forEach((edge, idx) => {
          const src = String(edge.source || '').toLowerCase();
          const tgt = String(edge.target || '').toLowerCase();

          // Cytoscape will crash if source or target node does not exist in elements
          if (nodeIds.has(src) && nodeIds.has(tgt)) {
            elements.push({
              data: {
                id: `edge-${src}-${tgt}-${idx}`,
                source: src,
                target: tgt,
                calls: edge.call_count || 1,
                type: edge.type || 'http',
              },
            });
          }
        });
      } else {
        // Fallback default topology mesh
        const defaultNodes = ['gateway', 'orders', 'payments', 'inventory', 'notifications'];
        defaultNodes.forEach((id) => {
          nodeIds.add(id);
          elements.push({
            data: { id, label: id.toUpperCase(), type: 'service', status: 'healthy', latency: 3 },
          });
        });
        elements.push(
          { data: { id: 'e1', source: 'gateway', target: 'orders' } },
          { data: { id: 'e2', source: 'orders', target: 'payments' } },
          { data: { id: 'e3', source: 'orders', target: 'inventory' } },
          { data: { id: 'e4', source: 'gateway', target: 'notifications' } }
        );
      }

      // Initialize Cytoscape in Light Theme
      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: 'node',
            style: {
              label: 'data(label)',
              color: '#0f172a',
              'font-family': 'JetBrains Mono, monospace',
              'font-size': '11px',
              'font-weight': 600,
              'text-valign': 'center',
              'text-halign': 'center',
              'background-color': '#ffffff',
              'border-width': 1.5,
              'border-color': '#cbd5e1',
              width: 90,
              height: 42,
              shape: 'roundrectangle',
            },
          },
          {
            selector: 'node[status = "warning"]',
            style: {
              'border-color': '#f59e0b',
              'background-color': '#fffbeb',
            },
          },
          {
            selector: 'node[status = "critical"]',
            style: {
              'border-color': '#dc2626',
              'background-color': '#fef2f2',
            },
          },
          {
            selector: 'node:selected',
            style: {
              'border-width': 2.5,
              'border-color': '#4f46e5',
              'background-color': '#eef2ff',
            },
          },
          {
            selector: 'edge',
            style: {
              width: 1.5,
              'line-color': '#94a3b8',
              'target-arrow-color': '#94a3b8',
              'target-arrow-shape': 'triangle',
              'curve-style': 'bezier',
              'arrow-scale': 1.1,
            },
          },
          {
            selector: 'edge:selected',
            style: {
              width: 2.5,
              'line-color': '#4f46e5',
              'target-arrow-color': '#4f46e5',
            },
          },
        ],
        layout: {
          name: 'breadthfirst',
          directed: true,
          padding: 40,
          spacingFactor: 1.4,
        },
      });

      cy.on('tap', 'node', (evt) => {
        const nodeData = evt.target.data();
        setSelectedNodeInfo(nodeData);
        if (onSelectService) {
          onSelectService(nodeData.id);
        }
      });

      cyRef.current = cy;
    } catch (err: any) {
      console.error('Failed to render Cytoscape dependency graph:', err);
      setRenderError(err?.message || 'Graph layout initialization failed');
    }

    return () => {
      if (cyRef.current) {
        try {
          cyRef.current.destroy();
        } catch {
          // ignore
        }
      }
    };
  }, [graphData, services, selectedService]);

  const handleZoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.25);
  const handleZoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() * 0.8);
  const handleFit = () => cyRef.current?.fit(undefined, 40);

  return (
    <div className="glass-panel" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Network size={16} color="#0f172a" />
          <h3 style={{ fontSize: '0.925rem', fontWeight: 600 }}>System Dependency Graph & Blast Radius</h3>
        </div>

        {/* Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          {onReload && (
            <button onClick={onReload} className="btn btn-secondary btn-sm" title="Reload Topology">
              <RefreshCw size={13} className={isLoading ? 'spin-anim' : ''} />
            </button>
          )}
          <button onClick={handleZoomIn} className="btn btn-secondary btn-sm" title="Zoom In">
            <ZoomIn size={13} />
          </button>
          <button onClick={handleZoomOut} className="btn btn-secondary btn-sm" title="Zoom Out">
            <ZoomOut size={13} />
          </button>
          <button onClick={handleFit} className="btn btn-secondary btn-sm" title="Fit to View">
            <Maximize2 size={13} />
          </button>
        </div>
      </div>

      {renderError ? (
        <div
          style={{
            padding: '2rem',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 'var(--radius-sm)',
            color: '#991b1b',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertTriangle size={16} />
          <span>Unable to initialize topology visualization: {renderError}</span>
        </div>
      ) : (
        /* Graph Viewport */
        <div
          ref={containerRef}
          style={{
            width: '100%',
            height: '480px',
            backgroundColor: '#f8fafc',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            position: 'relative',
          }}
        />
      )}

      {/* Selected Node Details Drawer */}
      {selectedNodeInfo && (
        <div
          style={{
            backgroundColor: '#f8fafc',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            padding: '0.75rem 1rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>Selected Service:</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#0f172a' }}>
              {selectedNodeInfo.label || selectedNodeInfo.id}
            </span>
            <span className={`badge ${selectedNodeInfo.status === 'healthy' ? 'badge-healthy' : 'badge-warning'}`}>
              {selectedNodeInfo.status}
            </span>
          </div>

          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Probe Latency: {selectedNodeInfo.latency}ms
          </span>
        </div>
      )}
    </div>
  );
};
