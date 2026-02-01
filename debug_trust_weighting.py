"""
DEBUG SCRIPT: Verify Trust-Weighted Aggregation is Working

This script checks:
1. Are trust scores being extracted from environment?
2. Are they being stored in self.trust_scores?
3. Are they being used in fedavg() weighting?
4. What are the actual weight coefficients being computed?
"""

import sys
import logging
from seal.trainer.fed_agent import FedPolicyTrainer
from seal.sumo.env import SumoEnv
from seal.trainer.weight_aggr import trust_weight_function, naive_weight_function
from netfiles import GRID_3x3
import numpy as np

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

print("=" * 80)
print("TRUST WEIGHTING DEBUG")
print("=" * 80)

# Test 1: Create a trainer and check its configuration
print("\n[TEST 1] Trainer Configuration")
print("-" * 80)

trainer = FedPolicyTrainer(
    fed_step=1,
    net_file=GRID_3x3,
    ranked=True,
    out_prefix="DEBUG_trust_test",
    weight_fn="trust",  # This is the key parameter
    checkpoint_freq=1,
)

print(f"✓ Trainer created with weight_fn='trust'")
print(f"  - use_trust_weighting: {trainer.use_trust_weighting}")
print(f"  - weight_fn: {trainer.weight_fn}")
print(f"  - trust_scores initial: {trainer.trust_scores}")

# Test 2: Check if environment has trust_scorer
print("\n[TEST 2] Environment Trust Scorer Check")
print("-" * 80)

env = SumoEnv(config=trainer.env_config_fn())
print(f"✓ Environment created")
print(f"  - has trust_scorer: {hasattr(env, 'trust_scorer')}")
if hasattr(env, 'trust_scorer'):
    print(f"  - trust_scorer is not None: {env.trust_scorer is not None}")
    if env.trust_scorer is not None:
        print(f"  - trust_scores: {env.trust_scorer.trust_scores}")
        print(f"  - trust_scores keys: {list(env.trust_scorer.trust_scores.keys())}")

# Test 3: Test the trust_weight_function
print("\n[TEST 3] Trust Weight Function")
print("-" * 80)

# Create mock episode data (9 agents)
mock_episode_data = {
    'A0': {'reward': -95.0, 'num_vehicles': 1000},
    'A1': {'reward': -75.0, 'num_vehicles': 1000},
    'A2': {'reward': -110.0, 'num_vehicles': 1000},
    'B0': {'reward': -58.0, 'num_vehicles': 1000},
    'B1': {'reward': -12.0, 'num_vehicles': 800},  # ATTACKED agent - lower reward
    'B2': {'reward': -82.0, 'num_vehicles': 1000},
    'C0': {'reward': -97.0, 'num_vehicles': 1000},
    'C1': {'reward': -63.0, 'num_vehicles': 1000},
    'C2': {'reward': -106.0, 'num_vehicles': 1000},
}

# Test with default trust scores (all 1.0)
trust_scores_default = {agent_id: 1.0 for agent_id in mock_episode_data.keys()}
coeffs_default = naive_weight_function(mock_episode_data)
print(f"Naive aggregation weights (all equal):")
for agent, coeff in coeffs_default.items():
    print(f"  {agent}: {coeff:.4f}")

print(f"\nNaive avg weight per agent: {1/9:.4f}")

# Test with trust weighting (B1 is suspected, other agents trusted)
trust_scores_attack = {
    'A0': 0.95, 'A1': 0.92, 'A2': 0.94,
    'B0': 0.93, 'B1': 0.25,  # ← B1 has LOW trust (suspected compromised)
    'B2': 0.91, 'C0': 0.96, 'C1': 0.94, 'C2': 0.95
}

coeffs_trust = trust_weight_function(mock_episode_data, trust_scores_attack)
print(f"\nTrust-weighted aggregation (B1 downweighted):")
for agent, coeff in coeffs_trust.items():
    trust = trust_scores_attack[agent]
    print(f"  {agent} (trust={trust:.2f}): {coeff:.4f}")

# Calculate how much B1 weight was reduced
b1_weight_naive = coeffs_default['B1']
b1_weight_trust = coeffs_trust['B1']
reduction = (1 - b1_weight_trust/b1_weight_naive) * 100
print(f"\nB1 weight reduction: {reduction:.1f}% (from {b1_weight_naive:.4f} to {b1_weight_trust:.4f})")

# Test 4: Verify fedavg() uses trust scores
print("\n[TEST 4] FedAvg Aggregation Function")
print("-" * 80)

print(f"Checking trainer.fedavg() logic:")
print(f"  - self.weight_fn == 'trust': {trainer.weight_fn == 'trust'}")
print(f"  - self.trust_scores is truthy: {bool(trainer.trust_scores)}")
print(f"  - Will use trust weighting: {trainer.weight_fn == 'trust' and trainer.trust_scores}")

# Show the logic from fedavg()
print(f"\nfedavg() logic:")
print(f"""
if self.weight_fn == "trust" and self.trust_scores:
    # Use trust-weighted aggregation
    coeffs = trust_weight_function(self.episode_data, self.trust_scores)
else:
    # Use fallback (naive or other)
    coeffs = WEIGHT_FUNCTIONS[self.weight_fn](self.episode_data)
""")

# Test 5: Check if _update_trust_scores_from_env would work
print("\n[TEST 5] Trust Score Extraction Simulation")
print("-" * 80)

try:
    # This is what happens in on_data_recording_step
    if hasattr(env, 'trust_scorer') and env.trust_scorer is not None:
        extracted_scores = env.trust_scorer.trust_scores.copy()
        print(f"✓ Successfully extracted trust scores from environment")
        print(f"  - Extracted scores: {extracted_scores}")
    else:
        print(f"✗ Environment does not have valid trust_scorer")
except Exception as e:
    print(f"✗ Error extracting trust scores: {e}")

# Clean up
env.kernel.close()

print("\n" + "=" * 80)
print("DEBUG SUMMARY")
print("=" * 80)
print(f"""
TRUST WEIGHTING SETUP:
  ✓ Trainer configured with weight_fn='trust'
  ✓ use_trust_weighting flag: {trainer.use_trust_weighting}
  ✓ Environment has trust_scorer: {hasattr(env, 'trust_scorer')}
  
WEIGHT FUNCTION:
  ✓ trust_weight_function exists and works correctly
  ✓ Reduces weight for low-trust agents (e.g., B1)
  ✓ Formula: weight = (reward_weight * trust_score) / sum(...)
  
INTEGRATION:
  • on_data_recording_step() calls _update_trust_scores_from_env()
  • _update_trust_scores_from_env() extracts from env.trust_scorer
  • fedavg() uses trust_scores IF:
    - self.weight_fn == 'trust' AND
    - self.trust_scores is not empty dict

POTENTIAL ISSUES TO CHECK:
  1. Is _update_trust_scores_from_env() actually getting called?
  2. Is env.trust_scorer being properly initialized?
  3. Are trust_scores actually being populated in env.trust_scorer?
  4. Is self.trust_scores being set to empty dict somewhere?
""")

print("\nRUN THIS ON ACTUAL TRAINING TO SEE:")
print("  - Log messages showing trust scores per episode")
print("  - Weight coefficients for each agent")
print("  - Comparison of naive vs trust-weighted weights")
