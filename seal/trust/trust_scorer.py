"""
Trust Scorer Module for CyberNet

Detects cyberattacks on traffic light controllers by monitoring:
1. Queue Spillback: Sudden occupancy spikes in upstream neighbors
2. Flow Mismatch: Inflow ≠ Outflow (traffic disappears or congestion)
3. Phase Lock: Traffic light stuck in one phase (never changes)

Returns trust scores (0-1) with exponential decay for suspected compromised intersections.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, deque


class TrustScorer:
    """
    Computes trust scores for traffic lights based on observed behavior anomalies.
    
    Trust Signals Monitored:
    - Queue spillback: occupancy[upstream] - occupancy_baseline > threshold
    - Flow mismatch: |inflow - outflow| > threshold (network-wide)
    - Phase lock: phase unchanged for > max_stuck_steps
    
    Trust Score: Exponential moving average combining all signals
    - Starts at 1.0 (fully trusted)
    - Decays exponentially when anomalies detected
    - Recovers slowly when normal behavior resumes
    """
    
    def __init__(
        self,
        tls_graph: Dict[str, List[str]],
        tls_ids: List[str],
        window_size: int = 20,
        spillback_threshold: float = 0.15,
        phase_lock_threshold: int = 30,
        ema_alpha: float = 0.1,
        suspected_threshold: float = 0.5
    ):
        """
        Initialize Trust Scorer.
        
        Args:
            tls_graph: Adjacency dict {tls_id: [downstream_neighbors]}
            tls_ids: List of all TLS IDs in network
            window_size: Number of steps for baseline occupancy calculation
            spillback_threshold: Min occupancy increase to flag spillback
            phase_lock_threshold: Steps without phase change to flag lock
            ema_alpha: Exponential moving average coefficient (higher = faster decay)
            suspected_threshold: Trust score below which TLS is "suspected"
        """
        self.tls_graph = tls_graph
        self.tls_ids = set(tls_ids)
        self.window_size = window_size
        self.spillback_threshold = spillback_threshold
        self.phase_lock_threshold = phase_lock_threshold
        self.ema_alpha = ema_alpha
        self.suspected_threshold = suspected_threshold
        
        # Build reverse graph (incoming edges)
        self.reverse_graph: Dict[str, List[str]] = defaultdict(list)
        for tls_id, neighbors in tls_graph.items():
            for neighbor in neighbors:
                self.reverse_graph[neighbor].append(tls_id)
        
        # Trust scores (0-1, 1=fully trusted)
        self.trust_scores: Dict[str, float] = {tls_id: 1.0 for tls_id in tls_ids}
        
        # Occupancy history for baseline calculation
        self.occupancy_history: Dict[str, deque] = {
            tls_id: deque(maxlen=window_size) for tls_id in tls_ids
        }
        
        # Phase tracking for phase lock detection
        self.last_phase: Dict[str, str] = {}
        self.phase_stuck_count: Dict[str, int] = {tls_id: 0 for tls_id in tls_ids}
        
        # Anomaly flags
        self.is_suspected: Dict[str, bool] = {tls_id: False for tls_id in tls_ids}
        self.anomaly_signals: Dict[str, Dict[str, bool]] = {
            tls_id: {"spillback": False, "phase_lock": False, "flow_mismatch": False}
            for tls_id in tls_ids
        }
    
    def update(
        self,
        occupancies: Dict[str, float],
        phases: Dict[str, str]
    ) -> None:
        """
        Update trust scores based on current observations.
        
        Args:
            occupancies: {tls_id: occupancy_value} where occupancy in [0, 1]
            phases: {tls_id: phase_string} e.g. {"A0": "GGGgrrrrGGGgrrrr", ...}
        """
        # Update occupancy history
        for tls_id, occ in occupancies.items():
            if tls_id in self.occupancy_history:
                self.occupancy_history[tls_id].append(occ)
        
        # Detect anomalies
        for tls_id in self.tls_ids:
            anomalies = {
                "spillback": self._detect_spillback(tls_id, occupancies),
                "phase_lock": self._detect_phase_lock(tls_id, phases),
                "flow_mismatch": False  # Placeholder for flow-based detection
            }
            self.anomaly_signals[tls_id] = anomalies
            
            # Update phase tracking
            if tls_id in phases:
                self.last_phase[tls_id] = phases[tls_id]
        
        # Calculate trust scores with exponential decay
        for tls_id in self.tls_ids:
            has_anomalies = any(self.anomaly_signals[tls_id].values())
            
            if has_anomalies:
                # Decay trust (penalize anomalies)
                penalty = 0.3  # 30% trust loss per anomaly signal
                num_anomalies = sum(self.anomaly_signals[tls_id].values())
                decay_factor = (1 - penalty) ** num_anomalies
                
                # EMA: new_score = (1 - alpha) * old_score + alpha * decayed_score
                self.trust_scores[tls_id] = (
                    (1 - self.ema_alpha) * self.trust_scores[tls_id] +
                    self.ema_alpha * decay_factor
                )
            else:
                # Recover trust slowly when normal
                recovery_factor = 0.95  # 5% recovery per normal step
                self.trust_scores[tls_id] = (
                    (1 - self.ema_alpha) * self.trust_scores[tls_id] +
                    self.ema_alpha * (self.trust_scores[tls_id] * recovery_factor + 0.05)
                )
            
            # Clamp to [0, 1]
            self.trust_scores[tls_id] = max(0.0, min(1.0, self.trust_scores[tls_id]))
            
            # Update suspected flag
            self.is_suspected[tls_id] = self.trust_scores[tls_id] < self.suspected_threshold
    
    def _detect_spillback(
        self,
        tls_id: str,
        occupancies: Dict[str, float]
    ) -> bool:
        """
        Detect queue spillback: sudden occupancy spike in upstream neighbors.
        
        Spillback occurs when queues from downstream intersection back up.
        Upstream neighbors should show increased occupancy.
        """
        if len(self.occupancy_history[tls_id]) < self.window_size:
            return False  # Need baseline first
        
        # Get baseline (average occupancy from first half of window)
        baseline_samples = list(self.occupancy_history[tls_id])[:self.window_size // 2]
        baseline = np.mean(baseline_samples) if baseline_samples else 0.0
        
        # Current occupancy
        current_occ = occupancies.get(tls_id, 0.0)
        
        # Spillback = current significantly higher than baseline
        spillback = current_occ - baseline > self.spillback_threshold
        
        return spillback
    
    def _detect_phase_lock(
        self,
        tls_id: str,
        phases: Dict[str, str]
    ) -> bool:
        """
        Detect phase lock: traffic light stuck in one phase.
        
        If phase doesn't change for many consecutive steps, it's likely
        the controller is frozen (compromised).
        """
        current_phase = phases.get(tls_id, None)
        
        if current_phase is None:
            return False
        
        if tls_id not in self.last_phase:
            self.last_phase[tls_id] = current_phase
            self.phase_stuck_count[tls_id] = 0
            return False
        
        # Check if phase changed
        if current_phase == self.last_phase[tls_id]:
            self.phase_stuck_count[tls_id] += 1
        else:
            self.phase_stuck_count[tls_id] = 0
            self.last_phase[tls_id] = current_phase
        
        # Phase lock if stuck > threshold
        phase_lock = self.phase_stuck_count[tls_id] > self.phase_lock_threshold
        
        return phase_lock
    
    def get_trust_score(self, tls_id: str) -> float:
        """
        Get current trust score for a TLS.
        
        Returns:
            float: Trust score in [0, 1], where 1 = fully trusted, 0 = fully compromised
        """
        return self.trust_scores.get(tls_id, 1.0)
    
    def is_suspected_compromised(self, tls_id: str, threshold: Optional[float] = None) -> bool:
        """
        Check if a TLS is suspected to be compromised.
        
        Args:
            tls_id: Traffic light ID
            threshold: Override default threshold (defaults to self.suspected_threshold)
        
        Returns:
            bool: True if trust_score < threshold
        """
        if threshold is None:
            threshold = self.suspected_threshold
        
        return self.trust_scores.get(tls_id, 1.0) < threshold
    
    def get_all_trust_scores(self) -> Dict[str, float]:
        """
        Get all current trust scores.
        
        Returns:
            dict: {tls_id: trust_score}
        """
        return self.trust_scores.copy()
    
    def get_anomaly_signals(self, tls_id: str) -> Dict[str, bool]:
        """
        Get anomaly signals for a specific TLS.
        
        Returns:
            dict: {"spillback": bool, "phase_lock": bool, "flow_mismatch": bool}
        """
        return self.anomaly_signals.get(tls_id, {})
    
    def reset(self) -> None:
        """Reset all trust scores and histories for new episode."""
        self.trust_scores = {tls_id: 1.0 for tls_id in self.tls_ids}
        self.occupancy_history = {
            tls_id: deque(maxlen=self.window_size) for tls_id in self.tls_ids
        }
        self.last_phase = {}
        self.phase_stuck_count = {tls_id: 0 for tls_id in self.tls_ids}
        self.is_suspected = {tls_id: False for tls_id in self.tls_ids}
        self.anomaly_signals = {
            tls_id: {"spillback": False, "phase_lock": False, "flow_mismatch": False}
            for tls_id in self.tls_ids
        }
