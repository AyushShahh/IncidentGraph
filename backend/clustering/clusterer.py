"""HDBSCAN density clustering engine for grouping novel error candidates into incidents."""
from typing import List
import numpy as np
import hdbscan

from backend.clustering.candidate import IncidentCandidateData
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class HDBSCANIncidentClusterer:
    """Density-based clustering engine using HDBSCAN over normalized candidate embeddings.

    Supports formation of multi-candidate incident clusters as well as
    graceful handling of singleton outliers without dropping any errors.
    """

    def __init__(
        self,
        min_cluster_size: int = 2,
        min_samples: int = 1,
        cluster_selection_epsilon: float = 0.0,
        max_cluster_distance: float = 0.85,
    ):
        self.min_cluster_size = min_cluster_size or settings.HDBSCAN_MIN_CLUSTER_SIZE
        self.min_samples = min_samples or settings.HDBSCAN_MIN_SAMPLES
        self.cluster_selection_epsilon = (
            cluster_selection_epsilon
            if cluster_selection_epsilon is not None
            else settings.HDBSCAN_CLUSTER_SELECTION_EPSILON
        )
        self.max_cluster_distance = (
            max_cluster_distance
            if max_cluster_distance is not None
            else getattr(settings, "HDBSCAN_MAX_CLUSTER_DISTANCE", 0.85)
        )

    def cluster_candidates(
        self,
        candidates: List[IncidentCandidateData],
    ) -> List[List[IncidentCandidateData]]:
        """Cluster a list of candidates into one or more groups.

        Each group represents an incident to be created. Outliers (label == -1)
        and clusters whose members exceed max_cluster_distance are evaluated
        with cosine cohesion fallback so related errors merge while unrelated errors remain distinct.

        Args:
            candidates: List of IncidentCandidateData with embeddings populated.

        Returns:
            List of candidate groups (List[List[IncidentCandidateData]]).
        """
        if not candidates:
            return []

        if len(candidates) == 1:
            return [[candidates[0]]]

        # Verify all candidates have embeddings
        missing_embeddings = [c for c in candidates if c.embedding is None]
        if missing_embeddings:
            raise ValueError(
                f"{len(missing_embeddings)} candidates are missing embeddings before clustering"
            )

        # Build feature matrix
        embeddings_matrix = np.array([c.embedding for c in candidates], dtype=np.float64)

        # If pool is smaller than configured min_cluster_size, dynamically adjust
        effective_min_cluster_size = min(self.min_cluster_size, len(candidates))

        logger.info(
            "Running HDBSCAN on %d candidates (min_cluster_size=%d, min_samples=%d)",
            len(candidates),
            effective_min_cluster_size,
            self.min_samples,
        )

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=effective_min_cluster_size,
            min_samples=self.min_samples,
            metric="euclidean",
            cluster_selection_epsilon=self.cluster_selection_epsilon,
            allow_single_cluster=True,
        )

        labels = clusterer.fit_predict(embeddings_matrix)

        clusters_map: dict[int, List[IncidentCandidateData]] = {}
        singletons: List[IncidentCandidateData] = []

        for candidate, label in zip(candidates, labels):
            if label == -1:
                singletons.append(candidate)
            else:
                if label not in clusters_map:
                    clusters_map[label] = []
                clusters_map[label].append(candidate)

        # Validate composite clusters to ensure cohesion
        result: List[List[IncidentCandidateData]] = []
        valid_clusters: List[List[IncidentCandidateData]] = []

        for cluster_id, members in clusters_map.items():
            if len(members) > 1:
                member_vecs = np.array([m.embedding for m in members], dtype=np.float64)
                diffs = member_vecs[:, np.newaxis, :] - member_vecs[np.newaxis, :, :]
                dists = np.sqrt(np.sum(diffs ** 2, axis=-1))
                max_dist = float(np.max(dists))

                if max_dist > self.max_cluster_distance:
                    logger.info(
                        "Cluster %d max pairwise distance %.3f exceeds %.3f; splitting into singletons",
                        cluster_id,
                        max_dist,
                        self.max_cluster_distance,
                    )
                    for m in members:
                        singletons.append(m)
                else:
                    valid_clusters.append(members)
            else:
                valid_clusters.append(members)

        # Attempt to merge outlier singletons into valid clusters if within max_cluster_distance
        remaining_singletons: List[IncidentCandidateData] = []
        for s in singletons:
            s_vec = np.array(s.embedding, dtype=np.float64)
            merged = False
            for cluster in valid_clusters:
                c_vecs = np.array([m.embedding for m in cluster], dtype=np.float64)
                diffs = c_vecs - s_vec
                dists = np.sqrt(np.sum(diffs ** 2, axis=-1))
                if np.max(dists) <= self.max_cluster_distance:
                    cluster.append(s)
                    merged = True
                    break
            if not merged:
                remaining_singletons.append(s)

        result.extend(valid_clusters)
        for s in remaining_singletons:
            result.append([s])

        logger.info(
            "Clustering completed: formed %d incident clusters from %d candidates",
            len(result),
            len(candidates),
        )

        return result


incident_clusterer = HDBSCANIncidentClusterer()
