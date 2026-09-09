"""In-memory symbol table and code navigation index.

Enables lightning-fast, exact and fuzzy symbol resolution, definition lookup,
and route registry across all indexed services.
"""
from typing import Dict, List, Optional, Set
from backend.core.logging import get_logger
from backend.repository.schemas import RouteInfo, SymbolDefinition, SymbolType

logger = get_logger(__name__)


class SymbolIndex:
    """Central in-memory index for all code symbols, methods, classes, and HTTP routes."""

    def __init__(self) -> None:
        # All symbols: id (service:file:name) -> SymbolDefinition
        self._symbols: Dict[str, SymbolDefinition] = {}
        # Exact name index: symbol_name.lower() -> list of symbol keys
        self._name_index: Dict[str, List[str]] = {}
        # Service index: service_name -> list of symbol keys
        self._service_index: Dict[str, Set[str]] = {}
        # File index: (service_name, file_path) -> list of symbol keys
        self._file_index: Dict[tuple[str, str], Set[str]] = {}
        # Service routes index: service_name -> list of RouteInfo
        self._service_routes: Dict[str, List[RouteInfo]] = {}

    def add_symbols(self, symbols: List[SymbolDefinition]) -> None:
        """Register a collection of extracted symbols into the index."""
        for sym in symbols:
            key = f"{sym.service_name}:{sym.file_path}:{sym.name}:{sym.start_line}"
            self._symbols[key] = sym

            # Name index
            name_lower = sym.name.lower()
            if name_lower not in self._name_index:
                self._name_index[name_lower] = []
            if key not in self._name_index[name_lower]:
                self._name_index[name_lower].append(key)

            # Also index by base name if qualified (e.g. Class.method -> method)
            if "." in name_lower:
                base_name = name_lower.split(".")[-1]
                if base_name not in self._name_index:
                    self._name_index[base_name] = []
                if key not in self._name_index[base_name]:
                    self._name_index[base_name].append(key)

            # Service index
            svc = sym.service_name.lower()
            if svc not in self._service_index:
                self._service_index[svc] = set()
            self._service_index[svc].add(key)

            # File index
            file_key = (svc, sym.file_path)
            if file_key not in self._file_index:
                self._file_index[file_key] = set()
            self._file_index[file_key].add(key)

            # Route registration
            if sym.route_info:
                if svc not in self._service_routes:
                    self._service_routes[svc] = []
                # Avoid duplicate routes
                existing = any(
                    r.method == sym.route_info.method and r.path == sym.route_info.path
                    for r in self._service_routes[svc]
                )
                if not existing:
                    self._service_routes[svc].append(sym.route_info)

    def remove_service_symbols(self, service_name: str) -> None:
        """Purge all symbols associated with a specific service."""
        svc = service_name.lower()
        keys_to_remove = list(self._service_index.get(svc, set()))
        for key in keys_to_remove:
            sym = self._symbols.pop(key, None)
            if sym:
                name_lower = sym.name.lower()
                if name_lower in self._name_index and key in self._name_index[name_lower]:
                    self._name_index[name_lower].remove(key)
                if "." in name_lower:
                    base = name_lower.split(".")[-1]
                    if base in self._name_index and key in self._name_index[base]:
                        self._name_index[base].remove(key)

        self._service_index.pop(svc, None)
        # Purge file index
        file_keys = [k for k in self._file_index if k[0] == svc]
        for fk in file_keys:
            self._file_index.pop(fk, None)

        self._service_routes.pop(svc, None)

    def remove_file_symbols(self, service_name: str, file_path: str) -> None:
        """Purge symbols associated with a single file within a service."""
        svc = service_name.lower()
        file_key = (svc, file_path)
        keys_to_remove = list(self._file_index.get(file_key, set()))

        for key in keys_to_remove:
            sym = self._symbols.pop(key, None)
            if sym:
                name_lower = sym.name.lower()
                if name_lower in self._name_index and key in self._name_index[name_lower]:
                    self._name_index[name_lower].remove(key)
                if "." in name_lower:
                    base = name_lower.split(".")[-1]
                    if base in self._name_index and key in self._name_index[base]:
                        self._name_index[base].remove(key)
                if svc in self._service_index:
                    self._service_index[svc].discard(key)

        self._file_index.pop(file_key, None)

    def find_symbol(
        self,
        name: str,
        service: Optional[str] = None,
    ) -> List[SymbolDefinition]:
        """Find definitions of a symbol by exact or qualified name."""
        name_lower = name.strip().lower()
        keys = self._name_index.get(name_lower, [])
        results: List[SymbolDefinition] = []

        for k in keys:
            sym = self._symbols.get(k)
            if sym:
                if service is None or sym.service_name.lower() == service.lower():
                    results.append(sym)

        return results

    def search_symbols(
        self,
        query: str,
        service: Optional[str] = None,
        symbol_type: Optional[SymbolType] = None,
        limit: int = 20,
    ) -> List[SymbolDefinition]:
        """Search symbols via substring matching, with optional service and type filters."""
        query_lower = query.strip().lower()
        matches: List[SymbolDefinition] = []

        # Exact matches first
        exact_keys = self._name_index.get(query_lower, [])
        for k in exact_keys:
            sym = self._symbols.get(k)
            if sym and self._matches_filter(sym, service, symbol_type):
                matches.append(sym)
                if len(matches) >= limit:
                    return matches

        # Substring / prefix matches
        for sym in self._symbols.values():
            if sym in matches:
                continue
            if query_lower in sym.name.lower():
                if self._matches_filter(sym, service, symbol_type):
                    matches.append(sym)
                    if len(matches) >= limit:
                        return matches

        return matches

    def get_service_routes(self, service_name: str) -> List[RouteInfo]:
        """Retrieve all HTTP routes exposed by a given service."""
        return list(self._service_routes.get(service_name.lower(), []))

    def get_all_routes(self) -> Dict[str, List[RouteInfo]]:
        """Retrieve all exposed routes across all indexed services."""
        return {svc: list(routes) for svc, routes in self._service_routes.items()}

    def get_symbols_for_file(self, service_name: str, file_path: str) -> List[SymbolDefinition]:
        """Get all symbols defined within a specific file."""
        file_key = (service_name.lower(), file_path)
        keys = self._file_index.get(file_key, set())
        return [self._symbols[k] for k in keys if k in self._symbols]

    @property
    def total_symbols(self) -> int:
        """Total number of indexed symbols."""
        return len(self._symbols)

    @staticmethod
    def _matches_filter(
        sym: SymbolDefinition,
        service: Optional[str],
        symbol_type: Optional[SymbolType],
    ) -> bool:
        if service and sym.service_name.lower() != service.lower():
            return False
        if symbol_type and sym.symbol_type != symbol_type:
            return False
        return True


# Global shared in-memory symbol index
_symbol_index = SymbolIndex()


def get_symbol_index() -> SymbolIndex:
    """Obtain singleton symbol index instance."""
    return _symbol_index
