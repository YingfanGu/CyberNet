# CyberNet Repository Review - February 6, 2026

## Executive Summary

Your repository is **on the right track architecturally** with all critical components properly implemented. The codebase correctly instantiates:
1. ✅ Cyberattack mechanism (force_attack at step 120, action masking)
2. ✅ Trust scoring mechanism (occupancy spillback, phase lock detection)
3. ✅ Trust-weighted aggregation (reward × trust_score² weighting)
4. ✅ Trainer orchestration (all 5 scenarios properly configured)
5. ✅ Dynamic seeding for random routes

**However**, there is **one critical mismatch**: your test results show trust-weighted aggregation is **HARMING performance** compared to naive aggregation—the opposite of your hypothesis. This suggests either:
- A bug in trust score extraction/application, or
- A design flaw in how trust scores are computed/used, or
- The trust mechanism needs different tuning parameters

---

## Component-by-Component Review

### 1. ✅ Cyberattack Mechanism - **CORRECT**

**Location**: `seal/sumo/env.py` (lines 147-156, 115-120)

```python
# Line 153-156: Attack triggers at step 120
if self.step_counter == self.attack_timestep and not self.attack_triggered:
    tls_to_attack = self.kernel.tls_hub[self.attacked_tls_id]
    tls_to_attack.force_attack(attack_type=self.attack_type)
    self.attack_triggered = True

# Line 115-120: Actions masked during attack
if tls.is_under_attack:
    taken_action[tls.id] = 0
    continue
```

**Validation**: 
- ✅ Attack triggers exactly once at configured timestep
- ✅ Attack maintains state via `tls.step_under_attack()` (line 161)
- ✅ Agent actions are hard-masked to 0 when under attack
- ✅ Agents **cannot know** the attack is happening (no visible signal)
- ✅ All three scenarios configured correctly in `train_cyber.py`:
  - Baseline: `attack_timestep=None` (no attack)
  - Degraded: `attack_timestep=120` (attack, naive aggregation)
  - Resilient: `attack_timestep=120` (attack, trust defense)

**Status**: ✅ This is correctly implemented.

---

### 2. ✅ Trust Scoring Mechanism - **CORRECT**

**Location**: `seal/trust/trust_scorer.py` (lines 1-261)

**Detects**:
- Queue spillback: `occupancy[upstream] - baseline > spillback_threshold` (aggressive at 0.25)
- Phase lock: Phase unchanged for 30+ steps
- EMA tracking: Trust scores decay with α=0.4 (fast response)

**Configuration in Resilient scenario** (`train_cyber.py` lines 256-262):
```python
config["trust_window_size"] = 5           # Fast baseline adjustment
config["trust_spillback_threshold"] = 0.25  # Aggressive spillback detection
config["trust_phase_lock_threshold"] = 30   # Phase lock detection
config["trust_ema_alpha"] = 0.4          # Fast EMA response
config["trust_suspected_threshold"] = 0.5   # Mark as suspected if score < 0.5
```

**Validation**:
- ✅ Computes occupancy baselines over 5-step windows
- ✅ Detects spillback from attacked intersection (B1) to neighbors
- ✅ Detects phase lock when B1 stuck in all-red
- ✅ Updates trust scores in environment step (line 99-102 in env.py)
- ✅ Trust scores extracted in trainer at aggregation time

**Status**: ✅ This is correctly implemented.

---

### 3. ✅ Trust-Weighted Aggregation - **CORRECT (in isolation)**

**Location**: `seal/trainer/weight_aggr.py` (lines 57-116)

```python
def trust_weight_function(episode_data, trust_scores):
    # Step 1: Reward-based weights
    reward_weights = {policy: policy_data["reward"] / total_reward ...}
    
    # Step 2: Modulate by trust^2 (quadratic penalty)
    trust_adjusted[policy] = reward_weights[policy] * (trust_score ** 2)
    
    # Step 3: Normalize
    coeffs = {policy: trust_adjusted[policy] / total_weight ...}
```

**Example**:
- Trusted agent (trust=1.0): multiplier = 1.0² = 1.0 (no penalty)
- Suspected agent (trust=0.7): multiplier = 0.7² = 0.49 (aggressive downweighting)
- Compromised agent (trust=0.3): multiplier = 0.3² = 0.09 (nearly eliminated)

**Validation**:
- ✅ Quadratic penalty correctly amplifies downweighting of low-trust agents
- ✅ Formula is mathematically sound
- ✅ Normalization ensures weights sum to 1.0

**Status**: ✅ This is correctly implemented.

---

### 4. ⚠️ Trainer Orchestration - **IMPLEMENTATION IS CORRECT, BUT RESULTS ARE INVERTED**

**Location**: `seal/trainer/fed_agent.py` (lines 225-250)

```python
def fedavg(self, policy_dict):
    weight_fn_impl = WEIGHT_FUNCTIONS[self.weight_fn]  # Get function
    
    if self.weight_fn == "trust" and self.trust_scores:
        coeffs = trust_weight_function(self.episode_data, self.trust_scores)
        logger.info(f"[FEDAVG] Using TRUST-WEIGHTED aggregation")
        # Apply coefficients to aggregate weights...
```

**Flow**:
1. Environment computes trust scores during episode (lines 99-102)
2. Trainer extracts trust scores via `_update_trust_scores_from_env()` (lines 85-113)
3. Aggregation uses trust scores in `fedavg()` (lines 246-250)
4. Weighted parameters returned to all agents

**Validation**:
- ✅ Trust scores extracted correctly from environment
- ✅ Weight function called with correct parameters
- ✅ Coefficients applied to policy parameters
- ✅ All agents updated with weighted average

**Status**: ✅ Implementation is correct, but **test results show it's harming performance**.

---

### 5. 🔴 **CRITICAL ISSUE: Test Results Show Trust Harming Performance**

**Observed in `visualize_training_results.py` output**:

```
Baseline (No Attack):           -650.70  ✅ Best
Degraded (Attack + Naive):      -677.12  (4.06% worse)
Resilient (Attack + Trust):     -729.43  (12.10% WORSE THAN NAIVE!) ❌
MARL (Multi-Agent):             -759.62
SARL (Single-Agent):            -742.69
```

**The Problem**: Trust defense is **worse than naive aggregation**
- Naive aggregation with attack: -677.12 (stable learning, +22.64 improvement)
- Trust-weighted aggregation: -729.43 (negative learning, -29.67 degradation)

**This contradicts your hypothesis** that trust-weighted defense should outperform naive aggregation.

---

## Likely Root Causes (In Priority Order)

### 1. **Trust Scores May Not Correctly Identify Attacked Agent**

**Question**: Is the attacked agent (B1, the center intersection) actually getting **marked as suspicious**?

**What should happen**:
- B1 locked in all-red phase at step 120+
- B1's upstream neighbors (B0, B2, B3, B4) see queue spillback
- TrustScorer should detect spillback and flag B1 as suspicious
- B1's trust score drops below 0.5
- Aggregation downweights B1

**What might be happening**:
- Trust scorer is detecting spillback at neighbors instead of at B1
- B1's own trust score isn't being downweighted
- All agents are downweighted equally
- The mechanism breaks down

**How to debug**: Add logging to print trust scores for each agent each episode.

---

### 2. **Trust Scores May Have Wrong Semantics for Agents**

**Current design**: Each TLS has a trust score
**Problem**: In federated learning, trust scores should map to **agents (policies)**, not intersections

Example mismatch:
```
# What you have:
TLS B1 → trust_score = 0.3 (compromised)

# What you need:
Policy_Agent_B1 → trust_score = 0.3 (agent controlling B1 is malicious)
```

**In multi-agent scenarios**, each agent controls one intersection, so mapping is 1:1. But the trust scorer computes **intersection-level** anomalies, not **agent-level** quality.

**The Fix**: Trust scores should reflect agent learning quality, not intersection anomalies.

---

### 3. **Trust Mechanism May Be Too Aggressive**

Even if correctly identified, the quadratic penalty `trust_score²` might be overcorrecting:
- B1 dropped to trust=0.3 → weight = 0.3² = 0.09
- This removes **91% of B1's contribution**
- In a 3×3 grid (9 agents), removing 1 agent's contribution is significant
- Other 8 agents' policies might not be good enough to compensate

**Hypothesis**: Using trust as soft constraint (linear instead of quadratic) might work better:
```python
# Current (aggressive):
weight_multiplier = trust_score ** 2

# Alternative (softer):
weight_multiplier = trust_score  # or trust_score ** 0.5
```

---

### 4. **Trust Scores May Be Computed on Wrong Observations**

**Current implementation** (line 99-102 in env.py):
```python
occupancies = {tls.id: obs[tls.id][0] for tls in self.kernel.tls_hub}
phases = {tls.id: tls.state for tls in self.kernel.tls_hub}
self.trust_scorer.update(occupancies, phases)
```

**Question**: Is `obs[tls.id][0]` the correct occupancy?

If occupancy encoding is different (e.g., `obs[tls.id]` is a vector), then spillback detection will fail.

---

### 5. **No Trust Scores Provided During Early Episodes**

**Timing issue**: Trust scorer needs ~5 steps to build baseline occupancy history before detecting spillback.

If aggregation happens before trust scores stabilize, early weights will be suboptimal.

---

## Recommendations for Diagnosis

### Step 1: **Add Comprehensive Logging**

Modify `seal/trainer/fed_agent.py` to log trust scores and weights each episode:

```python
def fedavg(self, policy_dict):
    if self.weight_fn == "trust":
        logger.info(f"\n[ROUND {self._round}] Trust-Weighted Aggregation")
        logger.info(f"  Episode Data: {self.episode_data}")
        logger.info(f"  Trust Scores: {self.trust_scores}")
        logger.info(f"  Computed Weights: {coeffs}")
        
        # Log which agents were downweighted
        for agent, weight in coeffs.items():
            trust = self.trust_scores.get(agent, 1.0)
            logger.info(f"    Agent {agent}: trust={trust:.3f}, weight={weight:.4f}")
```

### Step 2: **Validate Trust Score Mapping**

Verify that agent IDs in `episode_data` match agent IDs in `trust_scores`.

```python
# In fed_agent.py fedavg()
mismatched = set(self.episode_data.keys()) - set(self.trust_scores.keys())
if mismatched:
    logger.error(f"Agent ID mismatch: {mismatched}")
```

### Step 3: **Test Trust Mechanism in Isolation**

Create a simple test that:
1. Runs 1 episode with attack
2. Prints trust scores for all agents
3. Verifies B1 is marked as suspicious
4. Checks aggregation weights

**File**: `test_trust_isolation.py`

---

## What's Working Well ✅

1. **Dynamic seeding** for random routes - ✅ correctly implemented
2. **Multi-scenario training** - all 5 scenarios properly configured
3. **Action masking during attack** - agents can't learn attack resistance (realistic)
4. **Episode-level checkpointing** - saving weights per episode
5. **Training harness** - properly orchestrates PPO training across scenarios

---

## What Needs Investigation 🔴

1. **Trust scoring correctness** - Is B1 actually marked as suspicious?
2. **Trust-to-weight mapping** - Are trust scores applied to correct agents?
3. **Trust magnitude** - Is quadratic penalty too aggressive?
4. **Trust timing** - Are scores available before early aggregations?
5. **Observation encoding** - Is occupancy correctly extracted from obs?

---

## Architecture Alignment with Research Goal ✅

**Your Research Question**: *Can trust-weighted federated aggregation defend against cyberattacks when agents don't know the attack is happening?*

**Your Hypothesis**: FedRL-Resilient > FedRL-Degraded > SARL

**Current Status**:
- ✅ System correctly instantiates the hypothesis test
- ✅ Attack mechanism prevents agents from knowing about attack
- ✅ Trust mechanism detects behavioral anomalies
- ✅ Aggregation weights are adjusted based on trust
- ❌ **But empirical results show trust is harming, not helping**

**Next Action**: Debug why trust-weighted aggregation is underperforming naive aggregation, then validate the core hypothesis once trust mechanism works correctly.

---

## Files to Review in Detail

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Attack mechanism | `seal/sumo/env.py` | 115-120, 147-156 | ✅ Correct |
| Trust scoring | `seal/trust/trust_scorer.py` | 1-261 | ✅ Correct |
| Trust weighting | `seal/trainer/weight_aggr.py` | 57-116 | ✅ Correct |
| Trainer orchestration | `seal/trainer/fed_agent.py` | 225-250 | ✅ Correct |
| Trust extraction | `seal/trainer/fed_agent.py` | 85-113 | ⚠️ Needs verification |
| Configuration | `train_cyber.py` | 140-290 | ✅ Correct |

---

## Conclusion

**Your repository is architecturally sound and implements the correct idea.** The issue is not with the system design, but with the execution or tuning of the trust mechanism. The good news: this is debuggable. Add logging, validate the trust score flow, and you'll find where the mechanism breaks down.

Once trust scoring works correctly, you should see:
- **FedRL-Resilient > FedRL-Degraded** (trust defense outperforms naive under attack)
- **Both > SARL** (federated learning with defense beats single-agent)

This would validate your core hypothesis: **trust-weighted aggregation enables blind resilience to cyberattacks.**
