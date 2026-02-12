# Trust Mechanism Debugging Guide

## Problem Statement

Your test results show:
- **Naive aggregation (Degraded)**: -677.12 reward ✅ Better
- **Trust-weighted aggregation (Resilient)**: -729.43 reward ❌ Worse

This is the **opposite** of your hypothesis. The trust mechanism is harming performance.

---

## Debugging Checklist

### 1. Verify Trust Scores Are Being Computed

**Where**: `seal/sumo/env.py` lines 99-102

```python
if self.trust_scorer is not None:
    occupancies = {tls.id: obs[tls.id][0] for tls in self.kernel.tls_hub}
    phases = {tls.id: tls.state for tls in self.kernel.tls_hub}
    self.trust_scorer.update(occupancies, phases)
```

**Test**: Add logging to verify this executes:

```python
# After line 102
if self.trust_scorer is not None:
    occupancies = {tls.id: obs[tls.id][0] for tls in self.kernel.tls_hub}
    phases = {tls.id: tls.state for tls in self.kernel.tls_hub}
    self.trust_scorer.update(occupancies, phases)
    
    # DEBUG: Print trust scores every 20 steps
    if self.step_counter % 20 == 0 and self.step_counter > 120:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[TRUST] Step {self.step_counter}: {self.trust_scorer.trust_scores}")
```

**Expected output** after step 120:
```
[TRUST] Step 140: {'B0': 1.0, 'B1': 0.3, 'B2': 1.0, ..., 'B8': 1.0}
```

B1 should have **low trust score** (< 0.5).

---

### 2. Verify B1 is Marked as Suspected

**Where**: `seal/trust/trust_scorer.py` - update method

**Test**: Check if TrustScorer is correctly detecting B1's anomalies:

```python
# In your test script or train loop, after running an episode:

trainer = ResilientTrainer(...)
result = trainer.train(1)  # Run 1 episode

# Access the environment
worker = trainer.ray_trainer.workers.local_worker()
env = worker.env

# Check B1's trust score
b1_trust = env.trust_scorer.trust_scores.get("B1", 1.0)
print(f"B1 Trust Score: {b1_trust}")

if b1_trust > 0.8:
    print("ERROR: B1 not marked as suspicious!")
else:
    print("OK: B1 properly downweighted")
```

**Expected**: `b1_trust < 0.5` after attack at step 120.

---

### 3. Verify Trust Scores Are Extracted in Trainer

**Where**: `seal/trainer/fed_agent.py` lines 85-113

```python
def _update_trust_scores_from_env(self) -> None:
    """Extract trust scores from environment's trust scorer."""
    ...
    if hasattr(env, 'trust_scorer') and env.trust_scorer is not None:
        self.trust_scores = env.trust_scorer.trust_scores.copy()
        logger.info(f"[TRUST_SCORES] Extracted: {self.trust_scores}")
```

**Test**: Check if trust scores are being extracted each aggregation:

```python
# The logging is already there, check your training logs for:
# [TRUST_SCORES] Extracted: {'B0': 1.0, 'B1': 0.3, ...}

# If you see:
# [TRUST_SCORES] FAILED - env.trust_scorer not available!

# Then the extraction is broken.
```

---

### 4. Verify Agent IDs Match Between Episode Data and Trust Scores

**Problem**: Episode data has agent names like `"B0"`, `"B1"`, etc.
But trust scores might have different naming.

**Test**:

```python
# In fed_agent.py fedavg() method, add:

def fedavg(self, policy_dict):
    logger.info(f"[FEDAVG] Episode data agents: {list(self.episode_data.keys())}")
    logger.info(f"[FEDAVG] Trust score agents: {list(self.trust_scores.keys())}")
    
    # Check for mismatch
    episode_agents = set(self.episode_data.keys())
    trust_agents = set(self.trust_scores.keys())
    
    missing_trust = episode_agents - trust_agents
    if missing_trust:
        logger.error(f"[FEDAVG] Missing trust scores for: {missing_trust}")
    
    extra_trust = trust_agents - episode_agents
    if extra_trust:
        logger.warning(f"[FEDAVG] Extra trust scores for: {extra_trust}")
```

**If mismatch exists**, the trust scores aren't being applied to the right agents.

---

### 5. Verify Trust Weights Are Actually Applied

**Where**: `seal/trainer/fed_agent.py` lines 246-250

```python
if self.weight_fn == "trust" and self.trust_scores:
    coeffs = trust_weight_function(self.episode_data, self.trust_scores)
    logger.info(f"[FEDAVG] Computed weights: {coeffs}")
```

**Test**: Add detailed weight logging:

```python
# In fed_agent.py fedavg(), after computing coeffs:

logger.info(f"\n[FEDAVG] Round {self._round} - Trust-Weighted Aggregation")
logger.info(f"  Method: {self.weight_fn}")

for agent in self.episode_data.keys():
    reward = self.episode_data[agent]["reward"]
    trust = self.trust_scores.get(agent, 1.0)
    weight = coeffs.get(agent, 0.0)
    
    logger.info(f"  {agent}:")
    logger.info(f"    Reward: {reward:.2f}")
    logger.info(f"    Trust:  {trust:.3f}")
    logger.info(f"    Weight: {weight:.4f}")
    logger.info(f"    Multiplier: {trust**2:.4f}")
```

**Expected output**:
```
[FEDAVG] Round 10 - Trust-Weighted Aggregation
  B0:
    Reward: -650.0
    Trust:  1.0
    Weight: 0.1234
    Multiplier: 1.0000
  B1:
    Reward: -720.0
    Trust:  0.3
    Weight: 0.0089
    Multiplier: 0.0900
```

B1 weight should be much lower than B0.

---

### 6. Verify Weight Normalization

**Problem**: If all agents have low trust (or mixed trust), normalization might produce unexpected results.

**Test**: Print intermediate calculation steps:

```python
# In weight_aggr.py trust_weight_function():

logger.info("[TRUST_WEIGHT] Computing trust-weighted coefficients")
logger.info(f"  Reward weights: {reward_weights}")
logger.info(f"  Trust adjusted: {trust_adjusted}")
logger.info(f"  Total weight: {total_weight}")
logger.info(f"  Final coeffs: {coeffs}")
```

**Look for**: Total weight being very small (all agents downweighted too much).

---

### 7. Compare Actual vs Expected Behavior

Create a minimal test:

**File**: `test_trust_debug.py`

```python
"""Minimal test to verify trust mechanism"""
import os
import sys

# Add project to path
sys.path.insert(0, r'f:\Research\networkCA\2026\CyberNet')

from netfiles import GRID_3x3
from train_cyber import train_resilient

# Run 5 episodes with debug logging
n_episodes = 5
train_resilient(
    net_file=GRID_3x3,
    ranked=True,
    n_episodes=n_episodes,
    fed_step=1
)

# Check output
import pandas as pd
csv_path = r"out/SMARTCOMP/data/FedRL/grid-3x3/Cyberattack_3x3_resilience_resilient_trust_ranked.csv"

if os.path.exists(csv_path):
    df = pd.read_csv(csv_path)
    print("\nFinal 3 episodes:")
    print(df[['round', 'episode_reward_mean', 'episode_reward_min', 'episode_reward_max']].tail(3))
    
    # Calculate trend
    early = df['episode_reward_mean'].iloc[0]
    late = df['episode_reward_mean'].iloc[-1]
    trend = late - early
    
    print(f"\nTrend: {early:.2f} → {late:.2f} ({trend:+.2f})")
    
    if trend < 0:
        print("❌ NEGATIVE TREND - Trust mechanism harming performance")
    else:
        print("✅ POSITIVE TREND - Trust mechanism helping")
else:
    print(f"CSV not found at {csv_path}")
```

**Run this to isolate the trust issue.**

---

## Systematic Debugging Flow

```
1. Does trust_scorer exist in environment?
   └─ YES → 2
   └─ NO  → Check: is use_trust_scoring=True in config?

2. Are trust_scores being computed?
   └─ YES → 3
   └─ NO  → Check: TrustScorer.update() implementation

3. Are trust_scores correct (B1 < 0.5 after attack)?
   └─ YES → 4
   └─ NO  → Check: Spillback/phase-lock detection logic

4. Are trust_scores extracted in trainer?
   └─ YES → 5
   └─ NO  → Check: _update_trust_scores_from_env() implementation

5. Do agent IDs match?
   └─ YES → 6
   └─ NO  → Rename agents to match

6. Are weights computed correctly?
   └─ YES → 7
   └─ NO  → Check: trust_weight_function() math

7. Are weights applied to aggregation?
   └─ YES → 8
   └─ NO  → Check: fedavg() uses coeffs

8. Does resilient outperform degraded?
   └─ YES → ✅ Trust mechanism works!
   └─ NO  → Trust mechanism is overcorrecting
             → Try: weight_multiplier = trust (not trust²)
             → Try: Different trust_ema_alpha (0.1 vs 0.4)
             → Try: Higher suspected_threshold (0.6 vs 0.5)
```

---

## Most Likely Root Causes (Ranked)

### 1. **B1 Trust Score Not Dropping** (40% probability)

**Cause**: Spillback detection threshold too high or occupancy extraction wrong.

**Fix**: Lower `trust_spillback_threshold` from 0.25 → 0.1

```python
config["trust_spillback_threshold"] = 0.1  # More sensitive
```

### 2. **Quadratic Penalty Too Aggressive** (35% probability)

**Cause**: B1 goes from trust=1.0 to 0.3, multiplier becomes 0.09 (removes 91%).

**Fix**: Use linear penalty instead:

```python
# In weight_aggr.py, change:
trust_adjusted[policy] = reward_weights[policy] * trust_score  # Not trust_score²
```

### 3. **Agent ID Mismatch** (15% probability)

**Cause**: Episode data uses "B0" but trust scores use different naming.

**Fix**: Add validation in fedavg():

```python
# Ensure all agents have trust scores
for agent in self.episode_data:
    if agent not in self.trust_scores:
        self.trust_scores[agent] = 1.0  # Default to full trust
```

### 4. **EMA Alpha Too Low During Early Training** (10% probability)

**Cause**: Trust scores don't update fast enough with α=0.4.

**Fix**: Increase alpha:

```python
config["trust_ema_alpha"] = 0.7  # Faster response
```

---

## Quick Diagnostics Commands

Run in your terminal:

```bash
# 1. Check if trust_scorer is initialized
grep -n "TrustScorer" seal/sumo/env.py

# 2. Check trust score updates
grep -n "trust_scorer.update" seal/sumo/env.py

# 3. Check trust weight function
grep -n "trust_weight_function" seal/trainer/weight_aggr.py

# 4. Check trainer trusts scores extraction
grep -n "_update_trust_scores_from_env" seal/trainer/fed_agent.py
```

---

## Next Steps

1. **Run `test_trust_debug.py`** to collect baseline data
2. **Add logging to `seal/sumo/env.py` line 102** to print trust scores
3. **Add logging to `seal/trainer/fed_agent.py` line 246** to print weights
4. **Run 1 episode of Resilient scenario** and review logs
5. **Identify which step fails**
6. **Apply fix and re-run**

Once trust mechanism works correctly, you should see:
- **FedRL-Resilient > FedRL-Degraded**
- This validates your research hypothesis

---

**Questions to ask yourself as you debug**:

- Is B1 marked as suspicious? (Yes/No)
- Are trust scores different for each agent? (Yes/No)
- Are weights proportional to trust? (Yes/No)
- Is Resilient improving while Degraded degrading? (Yes/No)

If all are **Yes**, your hypothesis is validated! 🎉
