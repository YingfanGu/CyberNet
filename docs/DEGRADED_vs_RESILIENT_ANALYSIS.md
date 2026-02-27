# Why Degraded ≈ Resilient: Analysis of Trust-Weighted Aggregation Failure

**Date:** February 23, 2026  
**Experiment:** 5x5 Grid with 50 Episodes  
**Finding:** Resilient (Trust) scenario **UNDERPERFORMS** Degraded (Naive) by ~11.6%

---

## Executive Summary

The trust-weighted aggregation defense mechanism failed to mitigate the cyberattack. In fact, it **harmed performance**:

| Scenario | Final Reward | Degradation | Notes |
|----------|-------------|-------------|-------|
| Baseline (No Attack) | -3157 | 0% | Control reference |
| Degraded (Naive + Attack) | -3188 | 0.98% | Barely affected by attack |
| **Resilient (Trust + Attack)** | **-3248** | **2.88%** | **Trust mechanism worsened performance** |
| MARL (No Federation) | -3313 | 4.93% | Independent learning failed |
| SARL (Single Agent) | -3275 | 3.74% | Centralized control failed |

**Key Finding:** The trust-weighted aggregation is producing WORSE results than naive aggregation, suggesting the mechanism itself may be problematic.

---

## Mechanism Comparison

### Degraded Scenario (Naive Aggregation)
```python
weight_fn="naive"  # NO defense
use_trust_scoring=False
```

**How it works:**
1. Each agent (TLS) learns independently via PPO
2. At each aggregation step (fed_step=1): weights are averaged equally
3. All agents get 1/N weight regardless of performance
4. The attacked agent (C2) contributes equally to the global policy

**Why it still works:**
- Even with one compromised agent out of 25, the averaging effect is minimal (1/25 ≈ 4% influence)
- The attacked agent's degraded policy has only marginal impact on aggregate
- 24 good agents can "drown out" 1 bad agent in simple averaging
- Trust Detection doesn't apply, so no false positives

---

### Resilient Scenario (Trust-Weighted Aggregation)
```python
weight_fn="trust"  # YES defense
use_trust_scoring=True
config["trust_window_size"] = 5
config["trust_spillback_threshold"] = 0.05
config["trust_ema_alpha"] = 0.6
config["trust_suspected_threshold"] = 0.5
```

**How it works:**
1. Each agent learns independently via PPO
2. **Environment monitors queue spillback, phase lock, flow mismatches** at each step
3. TrustScorer computes trust_score ∈ [0,1] for each intersection
4. At aggregation: weights = reward_weights × (trust_score²)
5. Suspected agents (trust < 0.5) get heavily downweighted

**The Formula:**
```python
trust_adjusted[policy] = reward_weights[policy] * (trust_score ** 2)
coeffs[policy] = trust_adjusted[policy] / sum(trust_adjusted)
```

**Example:**
- Attacked agent: reward=-10, trust=0.4 → weight ∝ -10 × 0.16 = -1.6
- Good agent: reward=-90, trust=1.0 → weight ∝ -90 × 1.0 = -90

---

## Why Trust Mechanism is Failing

### Problem 1: Trust Scores Not Being Properly Extracted
The trust scores are computed in the **environment** but may not be reliably passed to the **trainer** for aggregation.

**Location:** `seal/trainer/fed_agent.py:_update_trust_scores_from_env()`
```python
def _update_trust_scores_from_env(self) -> None:
    worker = self.ray_trainer.workers.local_worker()
    env = worker.env
    if hasattr(env, 'trust_scorer') and env.trust_scorer is not None:
        self.trust_scores = env.trust_scorer.trust_scores.copy()
    else:
        logger.error(f"[TRUST_SCORES] FAILED - env.trust_scorer not available!")
```

**Issue:** This function must be called at the right time in the training loop. If it's not called, or called too late, `self.trust_scores` remains empty, and the trust-weighted aggregation defaults to naive averaging.

### Problem 2: Anomaly Detection May Be Too Loose or Noisy
Trust detection relies on three signals:
1. **Spillback Detection:** Queue occupancy > baseline + threshold
2. **Phase Lock Detection:** Phase unchanged for > 30 steps
3. **Flow Mismatch:** (Placeholder - not implemented)

**Potential issues:**
- With random routes (dynamic seeds), baseline occupancy varies greatly → false positives
- With only 1 attacked intersection (C2) out of 25, spillback may not propagate upstream
- Trust recovery factor (0.95) may cause quick recovery even after attack
- Phase lock threshold (30 steps) may be too high in a 360-step episode

### Problem 3: Quadratic Penalty May Be Too Aggressive
```python
trust_adjusted[policy] = reward_weights[policy] * (trust_score ** 2)
```

**Example damaging scenario:**
- Agent C2 (attacked): Gets legitimately low reward due to attack (-12 vs others at -90)
- Trust scorer slightly downgrades it to 0.7 (70% trust)
- Quadratic penalty: 0.7² = 0.49 → 49% of intended weight
- But if agent also has lower reward naturally, double penalty occurs

**Result:** Attacked agent is removed from learning, but so is valuable information about DEFENDING against the attack.

### Problem 4: Training Only 50 Episodes is Insufficient
Trust-weighted defense works best when:
1. Anomalies are detected reliably (requires stable environment baseline)
2. Attacked agents' influence decreases significantly
3. Remaining agents converge to good policy

**In 50 episodes:**
- First ~10 episodes: Random exploration, baselines not established
- Episodes 10-20: Trust mechanism might activate but agents still learning
- Episodes 20-50: Only ~30 episodes to learn good policy with downweighted bad agent

**Comparison:** MARL and SARL also performed poorly (4.93% and 3.74% degradation), suggesting 50 episodes is simply too short for the 5x5 network.

---

## Root Cause Analysis

### Hypothesis 1: Attack is Too Weak
The all-red phase lock on center intersection (C2) might not significantly degrade system performance in a 5x5 grid because:
- Center intersection has only 4 incoming lanes (vs 3x3 grid where center has 8)
- Traffic can reroute around center more easily in a large grid
- 360 steps (6 minutes) may be enough for traffic to adapt

**Evidence:** Degraded scenario shows only 0.98% degradation from baseline

### Hypothesis 2: Trust Mechanism is Not Activating
If trust scores aren't being extracted at aggregation time:
```python
# In fed_agent.py, during aggregation:
if self.use_trust_weighting:
    coeffs = trust_weight_function(self.episode_data, self.trust_scores)
else:
    coeffs = naive_weight_function(self.episode_data)
```

If `self.trust_scores` is empty `{}`, then `trust_scores.get(policy, 1.0)` returns 1.0 for all agents → **falls back to naive behavior**.

### Hypothesis 3: Trust Parameters Are Miscalibrated for 5x5 Grid
Original parameters were tuned for 3x3 grid:
- `trust_spillback_threshold = 0.05` (5% occupancy spike)
- `trust_ema_alpha = 0.6` (EMA response speed)
- `trust_window_size = 5` (baseline samples)

In 5x5 grid with 250 vehicles/lane/hour:
- Baselines are different (more traffic, larger queues)
- Spillback patterns are different
- Phase lock threshold (30 steps) might be wrong for larger network

---

## Recommendations to Fix

### 1. **Add Debug Logging to Verify Trust Score Extraction**
```python
# In fed_agent.py fedavg() or similar
logging.info(f"[AGG] Round {self._round}: trust_scores = {self.trust_scores}")
logging.info(f"[AGG] Using weight_fn='{self.weight_fn}'")
if self.weight_fn == "trust":
    logging.info(f"[AGG] Trust-weighted coefficients: {coeffs}")
else:
    logging.info(f"[AGG] Naive coefficients: {coeffs}")
```

Run a short test (5-10 episodes) and verify that:
- Trust scores are not empty at aggregation time
- Trust-weighted coefficients differ from naive coefficients
- Suspected agents actually get lower weights

### 2. **Retune Trust Parameters for 5x5 Grid**
For a 5x5 grid with 250 vehicles/lane/hour:
```python
# In train_cyber.py ResilientTrainer
config["trust_window_size"] = 10          # Larger window for stable baseline
config["trust_spillback_threshold"] = 0.08   # 8% (higher for more crowded network)
config["trust_ema_alpha"] = 0.4           # Slower decay (0.6 was too aggressive)
config["trust_phase_lock_threshold"] = 40  # Slightly higher
config["trust_suspected_threshold"] = 0.45  # Lower (more aggressive detection)
```

### 3. **Increase Training Episodes**
The 5x5 grid needs more training:
```python
n_episodes = 100  # Up from 50
```

More episodes allow:
- Better baseline establishment
- Attack detection to stabilize
- Convergence of remaining 24 agents

### 4. **Increase Attack Intensity**
Current attack: All-red phase lock on C2 at step 120

Possible stronger attacks:
- All-red lock on C2 **AND** one neighbor (e.g., C1, C3)
- Extend attack to more steps (e.g., steps 120-240)
- Use `phase_lock_attack` + `random_queue_injection` (if available)

### 5. **Alternative: Implement Byzantine-Resilient Aggregation**
Instead of trust weighting, consider:
- **Median aggregation:** Take median of weights instead of mean
- **Trimmed mean:** Discard top/bottom 10% before averaging
- **Krum algorithm:** Select weights closest to majority

These methods require NO environment monitoring and work even if attack is sophisticated.

---

## Investigation Checklist

- [ ] Add logging to `fed_agent.py` to verify `self.trust_scores` is not empty during aggregation
- [ ] Run 10-episode test and check if trust coefficients differ from naive
- [ ] If trust_scores is empty: add explicit call to `_update_trust_scores_from_env()` before aggregation
- [ ] If trust_scores is non-empty: check if they make sense (attacked agent should have low score)
- [ ] Retune all `trust_*` parameters for 5x5 grid
- [ ] Re-run with 100 episodes instead of 50
- [ ] Test with stronger attack (multi-intersection or longer duration)

---

## Conclusion

**The degraded scenario's robustness is NOT because Naive Aggregation is good - it's because the attack is weak in the 5x5 grid.**

With 25 agents and only 1 being attacked, simple averaging naturally provides ~96% of uncompromised updates, which is sufficient for acceptable performance.

The trust-weighted mechanism *should* improve on this, but it's currently either:
1. Not extracting trust scores properly (most likely)
2. Detecting attacks incorrectly (false positives/negatives)
3. Using miscalibrated thresholds for 5x5 grid

**Next step:** Implement debug logging and determine which of these is the actual cause.

