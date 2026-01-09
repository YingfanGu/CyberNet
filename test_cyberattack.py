"""
Test script to verify the cyberattack mechanism works correctly.

This script runs a 3x3 grid simulation with a cyberattack triggered at a specific timestep.
It logs queue lengths and phase states to verify:
1. Attack is triggered at the correct timestep
2. Attacked TLS enters all-red state
3. Queue buildup occurs at attacked intersection and neighbors
"""

import os
import sys
import pandas as pd
from netfiles import GRID_3x3
from seal.sumo.env import SumoEnv
from seal.logging import logging

# Configuration
HORIZON = 360
ATTACK_TIMESTEP = 120  # Attack at step 120 (after 2 minutes of normal operation)
ATTACKED_TLS_ID = "B1"  # Center intersection in 3x3 grid (valid IDs: A0-A2, B0-B2, C0-C2)
ATTACK_TYPE = "all_red"

def run_test():
    """Run a single episode with cyberattack and log results."""
    
    # Environment configuration
    env_config = {
        "net-file": GRID_3x3,
        "horizon": HORIZON,
        "ranked": False,
        "rand_routes_on_reset": True,
        "rand_route_args": {
            "vehicles_per_lane_per_hour": 360,
        },
        # Cyberattack configuration
        "attack_timestep": ATTACK_TIMESTEP,
        "attacked_tls_id": ATTACKED_TLS_ID,
        "attack_type": ATTACK_TYPE,
    }
    
    # Create environment
    env = SumoEnv(config=env_config)
    
    # Tracking lists
    results = {
        "step": [],
        "attacked_phase": [],
        "attacked_occupancy": [],
        "attacked_halted_occupancy": [],
        "attacked_under_attack": [],
        "center_total_occupancy": [],
        "network_avg_occupancy": [],
    }
    
    # Get the attacked TLS object
    attacked_tls = env.kernel.tls_hub[ATTACKED_TLS_ID]
    
    logging.info(f"Starting test run with attack at timestep {ATTACK_TIMESTEP}")
    logging.info(f"Attacked TLS: {ATTACKED_TLS_ID}")
    logging.info(f"Network file: {GRID_3x3}")
    logging.info(f"Horizon: {HORIZON} steps\n")
    
    # Run episode
    obs = env.reset()
    done = False
    step = 0
    
    while not done:
        # Take random actions (no policy)
        action_dict = {tls.id: 0 for tls in env.kernel.tls_hub}
        obs, reward, done, info = env.step(action_dict)
        
        # Track metrics
        attacked_obs = obs[ATTACKED_TLS_ID]
        results["step"].append(step)
        results["attacked_phase"].append(attacked_tls.phase)
        results["attacked_occupancy"].append(attacked_obs[0])  # LANE_OCCUPANCY
        results["attacked_halted_occupancy"].append(attacked_obs[1])  # HALTED_LANE_OCCUPANCY
        results["attacked_under_attack"].append(info[ATTACKED_TLS_ID]["under_attack"])
        
        # Calculate network metrics
        occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
        results["center_total_occupancy"].append(
            attacked_obs[0] + attacked_obs[1]
        )
        results["network_avg_occupancy"].append(sum(occupancies) / len(occupancies))
        
        # Log key moments
        if step == ATTACK_TIMESTEP:
            logging.info(f"\n[ATTACK TRIGGERED] Step {step}")
            logging.info(f"  Attacked TLS phase: {attacked_tls.phase}")
            logging.info(f"  Attacked TLS occupancy: {attacked_obs[0]:.3f}")
            logging.info(f"  Under attack: {info[ATTACKED_TLS_ID]['under_attack']}\n")
        
        if step % 60 == 0 and step > 0:
            logging.info(f"Step {step}: avg occupancy={results['network_avg_occupancy'][-1]:.3f}, "
                        f"attacked_occupancy={attacked_obs[0]:.3f}, "
                        f"under_attack={info[ATTACKED_TLS_ID]['under_attack']}")
        
        step += 1
        done = done["__all__"]
    
    env.close()
    
    # Save results to CSV
    df = pd.DataFrame(results)
    output_file = "cyberattack_test_results.csv"
    df.to_csv(output_file, index=False)
    logging.info(f"\nResults saved to {output_file}")
    
    # Print summary
    print("\n" + "="*80)
    print("CYBERATTACK TEST SUMMARY")
    print("="*80)
    
    pre_attack = df[df["step"] < ATTACK_TIMESTEP]
    post_attack = df[df["step"] >= ATTACK_TIMESTEP]
    
    print(f"\nPre-Attack (steps 0-{ATTACK_TIMESTEP-1}):")
    print(f"  Avg network occupancy: {pre_attack['network_avg_occupancy'].mean():.4f}")
    print(f"  Avg attacked TLS occupancy: {pre_attack['attacked_occupancy'].mean():.4f}")
    
    print(f"\nPost-Attack (steps {ATTACK_TIMESTEP}-{step-1}):")
    print(f"  Avg network occupancy: {post_attack['network_avg_occupancy'].mean():.4f}")
    print(f"  Avg attacked TLS occupancy: {post_attack['attacked_occupancy'].mean():.4f}")
    print(f"  Avg attacked TLS halted occupancy: {post_attack['attacked_halted_occupancy'].mean():.4f}")
    print(f"  Under attack count: {post_attack['attacked_under_attack'].sum()} / {len(post_attack)} steps")
    
    occupancy_increase = (post_attack['network_avg_occupancy'].mean() - 
                         pre_attack['network_avg_occupancy'].mean())
    print(f"\nNetwork occupancy increase: {occupancy_increase:+.4f}")
    print("="*80)

if __name__ == "__main__":
    run_test()
