"""Static dependency graph engine and blast radius analyzer using NetworkX.

Completely dynamic and domain-agnostic: builds directed interaction graphs for
any arbitrary set of services and endpoints without hardcoded topologies.
"""
from typing import Any, Dict, List, Optional, Set
import networkx as nx

from backend.core.logging import get_logger
from backend.repository.parser import OutboundCallInfo
from backend.repository.schemas import (
    BlastRadiusResult,
    DependencyEdge,
    DependencyEdgeType,
    DependencyNode,
    RouteInfo,
)

logger = get_logger(__name__)


class DependencyGraph:
    """Directed dependency graph representing inter-service communications and blast radius."""

    def __init__(self) -> None:
        # Directed graph: Edge (A, B) means "A calls B" (A depends on B)
        self._graph = nx.DiGraph()
        # Service exposed routes: service_name -> list of RouteInfo
        self._service_routes: Dict[str, List[RouteInfo]] = {}

    def clear(self) -> None:
        """Reset the graph."""
        self._graph.clear()
        self._service_routes.clear()

    def add_service_node(self, service_name: str, exposed_routes: Optional[List[RouteInfo]] = None) -> None:
        """Register a service node in the graph with its exposed routes."""
        svc = service_name.lower()
        if not self._graph.has_node(svc):
            self._graph.add_node(svc, type="service")

        if exposed_routes is not None:
            self._service_routes[svc] = list(exposed_routes)

    def build_from_parsed_data(
        self,
        service_names: List[str],
        service_routes: Dict[str, List[RouteInfo]],
        outbound_calls: List[OutboundCallInfo],
    ) -> None:
        """Reconstruct the entire dependency graph from parsed routes and outbound calls.

        Works dynamically for any arbitrary collection of services.
        """
        self.clear()

        # 1. Add all service nodes
        for svc in service_names:
            routes = service_routes.get(svc.lower(), [])
            self.add_service_node(svc, routes)

        # 2. Resolve outbound calls to target services
        known_services = {s.lower() for s in service_names}

        for call in outbound_calls:
            caller = str(call.caller_service).strip().lower()
            target: Optional[str] = None
            edge_type = DependencyEdgeType.HTTP

            # Case A: Explicit service hint (e.g. from host in URL or ENV var name)
            if call.target_service_hint and isinstance(call.target_service_hint, str):
                hint_clean = call.target_service_hint.strip().lower()
                if hint_clean in known_services:
                    target = hint_clean

            # Case B: Route path matching across known exposed routes
            elif call.target_url_or_path:
                cleaned_path = self._extract_path(call.target_url_or_path)
                if cleaned_path:
                    for svc, routes in self._service_routes.items():
                        if svc == caller:
                            continue
                        for r in routes:
                            # Match endpoint prefix or exact path
                            if self._paths_match(cleaned_path, r.path):
                                target = svc
                                break
                        if target:
                            break

            # Case C: Kafka / Event topic
            elif call.call_type == "kafka" and call.topic:
                edge_type = DependencyEdgeType.ASYNC_EVENT

            # Add edge if a valid target was resolved and not a self-loop
            if target and target != caller:
                self.add_dependency_edge(
                    DependencyEdge(
                        source_service=caller,
                        target_service=target,
                        edge_type=edge_type,
                        protocol="http" if edge_type == DependencyEdgeType.HTTP else "kafka",
                        endpoint=call.target_url_or_path,
                        method=call.http_method,
                        topic=call.topic,
                        details={"file": call.caller_file, "line": call.line_no},
                    )
                )

        logger.info(
            "Dependency graph constructed: %d nodes, %d edges.",
            self._graph.number_of_nodes(),
            self._graph.number_of_edges(),
        )

    def add_dependency_edge(
        self,
        edge: Optional[DependencyEdge] = None,
        *,
        caller: Optional[str] = None,
        callee: Optional[str] = None,
        source_service: Optional[str] = None,
        target_service: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        edge_type: DependencyEdgeType = DependencyEdgeType.HTTP,
        protocol: str = "http",
        topic: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a directed edge (source calls target) with metadata.

        Accepts either a `DependencyEdge` instance or keyword arguments.
        """
        if edge is None:
            src_val = source_service or caller
            tgt_val = target_service or callee
            if not src_val or not tgt_val:
                raise ValueError("Must provide either an edge or source/target service names.")
            edge = DependencyEdge(
                source_service=src_val,
                target_service=tgt_val,
                edge_type=edge_type,
                protocol=protocol,
                endpoint=endpoint,
                method=method,
                topic=topic,
                details=details or {},
            )

        src = edge.source_service.lower()
        tgt = edge.target_service.lower()

        if not self._graph.has_node(src):
            self.add_service_node(src)
        if not self._graph.has_node(tgt):
            self.add_service_node(tgt)

        # Merge or append edge data
        if self._graph.has_edge(src, tgt):
            existing_edges = self._graph[src][tgt].get("calls", [])
            existing_edges.append(edge.model_dump())
            self._graph[src][tgt]["calls"] = existing_edges
        else:
            self._graph.add_edge(src, tgt, calls=[edge.model_dump()], edge_type=edge.edge_type.value)

    def get_dependencies(self, service_name: str) -> List[str]:
        """Get downstream services that `service_name` directly calls (successors)."""
        svc = service_name.lower()
        if not self._graph.has_node(svc):
            return []
        return sorted(list(self._graph.successors(svc)))

    def get_dependents(self, service_name: str) -> List[str]:
        """Get upstream services that directly call `service_name` (predecessors)."""
        svc = service_name.lower()
        if not self._graph.has_node(svc):
            return []
        return sorted(list(self._graph.predecessors(svc)))

    def get_blast_radius(self, target_service: str) -> BlastRadiusResult:
        """Calculate the blast radius if `target_service` fails.

        Upstream callers (ancestors in graph) are affected because they call this service.
        """
        svc = target_service.lower()

        if not self._graph.has_node(svc):
            return BlastRadiusResult(
                target_service=target_service,
                impact_level="LOW",
                direct_callers=[],
                transitive_callers=[],
                downstream_dependencies=[],
                affected_routes=[],
                summary=f"Service '{target_service}' has no known callers or dependencies in topology.",
            )

        # Direct callers (predecessors)
        direct_callers = sorted(list(self._graph.predecessors(svc)))

        # Transitive callers: all nodes that have a directed path to `svc`
        # In NetworkX: ancestors(G, target) returns all nodes with path to target
        transitive_ancestors = nx.ancestors(self._graph, svc)
        transitive_callers = sorted(list(transitive_ancestors))

        # Downstream dependencies (what this service calls)
        downstream = sorted(list(self._graph.successors(svc)))

        # Collect affected routes (routes on target service + routes on direct callers)
        affected_routes: List[str] = []
        for r in self._service_routes.get(svc, []):
            affected_routes.append(f"[{svc.upper()}] {r.method} {r.path}")

        for caller in direct_callers:
            for r in self._service_routes.get(caller, []):
                affected_routes.append(f"[{caller.upper()}] {r.method} {r.path}")

        # Compute impact level
        total_affected = len(transitive_callers)
        if total_affected >= 3 or ("gateway" in transitive_callers and total_affected >= 2):
            impact_level = "CRITICAL"
        elif total_affected == 2:
            impact_level = "HIGH"
        elif total_affected == 1:
            impact_level = "MEDIUM"
        else:
            impact_level = "LOW"

        summary = (
            f"Failure in '{target_service}' impacts {len(transitive_callers)} upstream service(s) "
            f"({', '.join(transitive_callers) if transitive_callers else 'none'}). "
            f"Direct callers: {len(direct_callers)}; Downstream dependencies: {len(downstream)}."
        )

        return BlastRadiusResult(
            target_service=target_service,
            impact_level=impact_level,
            direct_callers=direct_callers,
            transitive_callers=transitive_callers,
            downstream_dependencies=downstream,
            affected_routes=affected_routes[:20],
            summary=summary,
        )

    def get_full_topology(self) -> Dict[str, Any]:
        """Export the full graph topology with centrality metrics."""
        in_centrality = nx.in_degree_centrality(self._graph) if len(self._graph) > 1 else {}
        out_centrality = nx.out_degree_centrality(self._graph) if len(self._graph) > 1 else {}

        nodes: List[Dict[str, Any]] = []
        for node in self._graph.nodes:
            routes = [r.model_dump() for r in self._service_routes.get(node, [])]
            node_data = DependencyNode(
                service_name=node,
                exposed_routes=self._service_routes.get(node, []),
                downstream_dependencies=list(self._graph.successors(node)),
                upstream_callers=list(self._graph.predecessors(node)),
                in_degree_centrality=round(in_centrality.get(node, 0.0), 3),
                out_degree_centrality=round(out_centrality.get(node, 0.0), 3),
            )
            nodes.append(node_data.model_dump())

        edges: List[Dict[str, Any]] = []
        for src, tgt, data in self._graph.edges(data=True):
            calls = data.get("calls", [])
            edges.append(
                {
                    "source": src,
                    "target": tgt,
                    "edge_type": data.get("edge_type", "http"),
                    "call_count": len(calls),
                    "details": calls,
                }
            )

        return {
            "total_nodes": self._graph.number_of_nodes(),
            "total_edges": self._graph.number_of_edges(),
            "nodes": nodes,
            "edges": edges,
        }

    # -------------------------------------------------------------------------
    # Path matching helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_path(url_or_path: str) -> Optional[str]:
        """Extract path component from URL or raw path."""
        if not url_or_path:
            return None
        # If full URL: http://service:8000/orders -> /orders
        if "://" in url_or_path:
            after_proto = url_or_path.split("://", 1)[1]
            if "/" in after_proto:
                return "/" + after_proto.split("/", 1)[1].split("?")[0]
            return "/"
        # Relative path
        clean = url_or_path.split("?")[0]
        if not clean.startswith("/"):
            clean = "/" + clean
        return clean

    @staticmethod
    def _paths_match(called_path: str, registered_route: str) -> bool:
        """Check if a called path matches a registered route pattern."""
        if called_path == registered_route:
            return True
        # Match parameterized routes, e.g. /orders/{order_id} with /orders
        reg_base = registered_route.split("/{")[0].rstrip("/")
        called_base = called_path.split("/{")[0].rstrip("/")
        if reg_base and called_base and reg_base == called_base:
            return True
        # Prefix matching for API namespaces
        if reg_base and called_base.endswith(reg_base):
            return True
        return False


# Global singleton dependency graph
_dependency_graph = DependencyGraph()


def get_dependency_graph() -> DependencyGraph:
    """Obtain singleton dependency graph instance."""
    return _dependency_graph
