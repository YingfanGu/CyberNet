# STEP 1: Cyberattack Mechanism Implementation Summary

**Date:** January 6, 2026  
**Status:** ✅ Complete  
**Files Modified:** 2  

---

## What Was Added

### 1. **Modified: `seal/sumo/kernel/trafficlight/light.py`**

Added attack-related attributes to TrafficLight class:
```python
self.is_under_attack: bool = False        # Flag indicating if TLS is under attack
self.attack_type: str = None              # Type: "all_red" or "stuck_phase"
```

Added three new methods:

#### `force_attack(attack_type: str = "all_red")`
- **Purpose:** Initiate a cyberattack on the traffic light
- **Behavior:** 
  - If `attack_type == "all_red"`: Forces phase to all-red state (closes intersection)
  - If `attack_type == "stuck_phase"`: Locks the current phase (inefficient control)
- **When called:** Once at attack timestep

#### `step_under_attack()`
- **Purpose:** Maintain attack state during simulation steps
- **Behavior:** Re-applies the attack constraint each step (continuously enforces all-red, prevents phase transitions)
- **When called:** Every simulation step while attacked

#### `clear_attack()`
- **Purpose:** Remove attack and return to normal operation
- **Behavior:** Resets `is_under_attack` and `attack_type` flags
- **When called:** Can be triggered by mitigation logic

---

### 2. **Modified: `seal/sumo/env.py`**

#### Added attack configuration parameters to `__init__`:
```python
self.attack_timestep: Optional[int] = config.get("attack_timestep", None)
self.attacked_tls_id: Optional[str] = config.get("attacked_tls_id", None)
self.attack_type: str = config.get("attack_type", "all_red")
self.attack_triggered = bool  # Track if attack has been triggered
```

These allow experiments to configure:
- **When** to attack (`attack_timestep`)
- **Which** intersection to attack (`attacked_tls_id`)
- **How** to attack (`attack_type`)

#### Modified `step()` method:
- Now calls `_handle_cyberattack()` before SUMO kernel step
- Added `"under_attack"` flag to info dict for tracking

#### Added `_handle_cyberattack()` method:
```python
def _handle_cyberattack(self) -> None:
    # Trigger attack if conditions are met
    if (self.attack_timestep is not None and 
        self.attacked_tls_id is not None and 
        self.step_counter == self.attack_timestep and 
        not self.attack_triggered):
        
        tls_to_attack = self.kernel.tls_hub[self.attacked_tls_id]
        tls_to_attack.force_attack(attack_type=self.attack_type)
        self.attack_triggered = True
    
    # Maintain attack state for all TLS under attack
    for tls in self.kernel.tls_hub:
        if tls.is_under_attack:
            tls.step_under_attack()
```

#### Modified `_do_action()` method:
- Added check: if TLS is under attack, skip the RL action
- Attack maintains control, RL cannot override

#### Modified info dict:
- Now includes `"under_attack": tls.is_under_attack` for each TLS

---

## How It Works

### **Normal Operation (no attack):**
```
Step 1-119: Normal traffic control
  ├─ RL agents take actions freely
  ├─ TLS phases change normally
  └─ Network operates smoothly

Step 120: ATTACK!
  ├─ _handle_cyberattack() detects attack timestep
  ├─ Attacked TLS transitions to all-red
  ├─ RL actions on that TLS are ignored
  └─ Queues begin to build up
  
Step 121+: Sustained Attack
  ├─ step_under_attack() maintains all-red state
  ├─ Attacked TLS stays frozen
  ├─ Neighbors must adapt
  └─ System either fails or recovers (depending on mitigation)
```

---

## Usage Example

```python
from seal.sumo.env import SumoEnv
from netfiles import GRID_3x3

# Configure environment with cyberattack
env_config = {
    "net-file": GRID_3x3,
    "horizon": 360,
    "ranked": False,
    # === Cyberattack configuration ===
    "attack_timestep": 120,        # Attack at step 120
    "attacked_tls_id": "C",        # Target center intersection
    "attack_type": "all_red",      # Force to all-red
}

env = SumoEnv(config=env_config)
obs = env.reset()

# Run simulation - attack happens automatically at step 120
for step in range(360):
    action = {tls.id: 0 for tls in env.kernel.tls_hub}  # Take random actions
    obs, reward, done, info = env.step(action)
    
    # Check if attack is active
    if info["C"]["under_attack"]:
        print(f"Step {step}: Intersection C is under attack!")
```

---

## What NOT to do Yet

❌ **DO NOT** run training with `train.py` yet  
❌ **DO NOT** modify FedRL weights based on attack  
❌ **DO NOT** implement trust scoring yet  

These will be done in **Steps 3-5**.

---

## Next: STEP 1.5 - Test Attack

The file `test_cyberattack.py` has been created to verify the attack works:

```bash
python test_cyberattack.py
```

This script will:
1. Run a 3×3 grid simulation
2. Trigger attack at step 120
3. Log queue buildup before/after attack
4. Save results to `cyberattack_test_results.csv`
5. Print a summary showing network degradation

**Expected output:**
- Pre-attack avg occupancy: ~0.10-0.20
- Post-attack avg occupancy: ~0.30-0.50 (network gets congested)
- Attacked TLS occupancy increases significantly

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      SumoEnv.step()                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ 1. _do_action()                                             │
│    ├─ For each TLS:                                          │
│    │  ├─ If under_attack: skip RL action (action = 0)      │
│    │  └─ Else: apply RL action                              │
│    └─ Return taken_actions                                  │
│                                                             │
│ 2. _handle_cyberattack()  ← NEW                             │
│    ├─ If step == attack_timestep:                           │
│    │  └─ tls.force_attack(attack_type)                      │
│    └─ For each tls under_attack:                            │
│       └─ tls.step_under_attack()                            │
│                                                             │
│ 3. kernel.step()                                            │
│    └─ SUMO advances simulation                              │
│                                                             │
│ 4. _observe() → obs                                         │
│                                                             │
│ 5. Build reward, done, info                                 │
│    └─ info includes under_attack flag                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Design Decisions

### **Why two methods for attack?**
- `force_attack()`: Called once to initiate attack state
- `step_under_attack()`: Called every step to maintain attack
- Separation allows for: different attack types, recovery logic, gradual failures

### **Why block RL actions?**
- If RL could override attack, it would just fix the problem immediately
- Attack needs to be real: RL actions are powerless against it
- Forces system-level (federated) adaptation, not individual agent adaptation

### **Why all_red instead of wrong phases?**
- All-red is objective: clearly broken (no vehicles pass)
- Wrong phases: harder to define, less reproducible
- All-red enables later "soft" attacks (inefficient phases) as extensions

---

## Files Created/Modified

| File | Status | Lines Changed |
|------|--------|----------------|
| `seal/sumo/kernel/trafficlight/light.py` | ✅ Modified | +50 |
| `seal/sumo/env.py` | ✅ Modified | +30 |
| `test_cyberattack.py` | ✅ Created | 150 |

**Total Changes:** 230 lines added  
**Complexity:** Low (no RL changes yet, just environment mechanics)

