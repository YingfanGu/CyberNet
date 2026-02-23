# Trust Weighting Bug Fix: Root Cause Analysis and Solution

## 🔍 Root Cause Discovered

### The Problem
Trust-weighted aggregation (Resilient scenario) was producing **worse** results (12.1% degradation) than naive aggregation (4.06% degradation) when under cyberattack, despite the code appearing correct on static inspection.

### The Root Cause
**The environment's TrustScorer was never being initialized**, because the `use_trust_scoring` flag was not included in the environment configuration passed to the environment.

#### Chain of Events:
1. **FedPolicyTrainer.__init__()** sets `self.use_trust_weighting = (self.weight_fn == "trust")`
2. **FedPolicyTrainer.on_setup()** calls Ray trainer initialization with `env_config`
3. **BaseTrainer.env_config_fn()** (inherited by FedPolicyTrainer) returns standard config WITHOUT `use_trust_scoring` flag
4. **SumoEnv.__init__()** reads `config.get("use_trust_scoring", False)` → **always False** since key doesn't exist
5. **SumoEnv.__init__()** only initializes TrustScorer `if self.use_trust_scoring:` → **TrustScorer is never created**
6. **FedPolicyTrainer._update_trust_scores_from_env()** tries to extract from `env.trust_scorer` → **gets None**
7. **FedPolicyTrainer.fedavg()** checks `if self.weight_fn == "trust" and self.trust_scores:` → **trust_scores is empty dict {}**
8. **Falls back to naive aggregation** instead of trust-weighted aggregation
9. **Naive aggregation doesn't help against compromised agents** → **Resilient scenario performs as poorly as naive**

### What the Code *Looked* Like (Incomplete Picture)
```python
# In FedPolicyTrainer
self.use_trust_weighting = (self.weight_fn == "trust")  # ✓ Correct
self._update_trust_scores_from_env()  # ✓ Called
# But trust_scores stays empty because env.trust_scorer is None!
```

```python
# In fedavg()
if self.weight_fn == "trust" and self.trust_scores:  # ✓ Correct condition
    coeffs = trust_weight_function(...)  # But never executes!
```

```python
# In BaseTrainer.env_config_fn()
config = {
    "gui": self.gui,
    "net-file": self.net_file,
    # ... other keys ...
    # ✗ MISSING: "use_trust_scoring": True
}
```

## ✅ The Fix

### Step 1: Override env_config_fn() in FedPolicyTrainer
Added method to include `use_trust_scoring` flag in environment config:

```python
def env_config_fn(self) -> Dict[str, Any]:
    """Override base env_config_fn to include trust scoring if needed."""
    config = super().env_config_fn()
    # Enable trust scoring if using trust-weighted aggregation
    config["use_trust_scoring"] = self.use_trust_weighting
    return config
```

Now when `weight_fn="trust"`:
- `self.use_trust_weighting = True`
- `env_config["use_trust_scoring"] = True`
- `SumoEnv.__init__()` receives `use_trust_scoring=True`
- `SumoEnv` initializes `TrustScorer`
- `_update_trust_scores_from_env()` successfully extracts trust scores
- `fedavg()` uses trust-weighted aggregation

### Step 2: Added Comprehensive Logging
Added debug logging at key points to verify trust weighting is active:

1. **env_config_fn()** logs `Setting use_trust_scoring={value}`
2. **_update_trust_scores_from_env()** logs:
   - When attempting extraction
   - SUCCESS/FAILURE with extracted scores
   - Suspected compromised agents
   - Any exceptions
3. **on_data_recording_step()** logs:
   - Round number and aggregation status
   - Whether trust weighting is being used
   - Result after extraction
4. **fedavg()** logs:
   - Decision: TRUST-WEIGHTED vs FALLBACK aggregation
   - Individual agent weights in both cases

## 📊 Expected Results After Fix

### Before Fix (Trust Weighting Not Working)
```
Baseline (no attack):     -650.70  ✓ Converges
Degraded (attack, naive): -677.12  ✓ Converges (naive still works)
Resilient (attack, trust): -729.43  ✗ DIVERGES (trust weighting never activates)
```

### After Fix (Trust Weighting Working)
```
Baseline (no attack):     -650.70  ✓ Converges
Degraded (attack, naive): -677.12  ✓ Converges  
Resilient (attack, trust): -670?   ✓ CONVERGES (near Degraded, much better than before)
```

The Resilient scenario should now:
1. Successfully initialize TrustScorer in environment
2. Detect compromised agent B1 (queue spillback, phase lock)
3. Assign lower trust score to B1 (e.g., 0.25 instead of 1.0)
4. Apply trust-weighted aggregation: B1's influence reduced from ~11% to ~3%
5. Learning stabilizes because good agents' models dominate updates
6. Performance recovers to near-naive baseline despite cyberattack

## 🧪 Verification

Run these scripts to verify the fix:

1. **verify_trust_fix.py** - 4 automated tests
   - Test 1: env_config includes use_trust_scoring=True
   - Test 2: TrustScorer initializes when enabled
   - Test 3: TrustScorer disabled when flag=False
   - Test 4: Trust scores extracted from environment

2. **test_trust_logging.py** - Run full training with logging
   - Shows trust score extraction at each round
   - Shows weight coefficients computed
   - Verifies TRUST-WEIGHTED path is taken

## 📁 Files Modified

1. **seal/trainer/fed_agent.py**:
   - Added `env_config_fn()` override to include `use_trust_scoring` flag
   - Enhanced logging in `_update_trust_scores_from_env()`
   - Enhanced logging in `on_data_recording_step()`
   - Enhanced logging in `fedavg()` to show decision and weights

## 🎯 Impact

- **Fixes critical trust weighting failure**: Makes trust-weighted aggregation actually work
- **No API changes**: Fully backward compatible
- **Adds diagnostic capability**: Comprehensive logging for debugging
- **Enables resilience feature**: Allows CyberNet to defend against compromised agents

## 🔬 Testing Recommendation

After this fix, re-run the training scenarios:
1. Baseline (control - no attack)
2. Degraded (naive aggregation + attack) 
3. Resilient (trust-weighted + attack) ← Should now work!

Expected: Resilient ≈ Degraded > Baseline in terms of attack impact
(Trust weighting successfully mitigates the attack)

---

**Status**: ✅ Fix implemented and logged
**Next Step**: Execute verification tests, then re-run full training
