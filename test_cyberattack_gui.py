"""
GUI Test script to visualize the cyberattack mechanism in SUMO.

This script runs the same attack test but with SUMO GUI enabled so you can
watch the traffic behavior before and after the attack is triggered.

Pre-attack (steps 0-119): Normal traffic flow
Attack trigger (step 120): Center intersection (B1) goes all-red
Post-attack (steps 120-359): Queue spillback cascades through network

Controls:
- Press SPACE to pause/resume simulation
- Right-click to inspect intersections
- Use speed slider in SUMO GUI to slow down/speed up
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
ATTACKED_TLS_ID = "B1"  # Center intersection in 3x3 grid
ATTACK_TYPE = "all_red"

def run_test_gui():
    """Run a single episode with cyberattack, visualized in SUMO GUI."""
    
    # Environment configuration with GUI enabled
    env_config = {
        "net-file": GRID_3x3,
        "gui": True,  # Enable SUMO GUI
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
    
    # Create environment with GUI
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
    
    logging.info(f"Starting GUI test run with attack at timestep {ATTACK_TIMESTEP}")
    logging.info(f"Attacked TLS: {ATTACKED_TLS_ID}")
    logging.info(f"Network file: {GRID_3x3}")
    logging.info(f"Horizon: {HORIZON} steps\n")
    logging.info("Watch the SUMO GUI window:")
    logging.info(f"  Steps 0-119: Normal traffic flow (pre-attack)")
    logging.info(f"  Step 120: {ATTACKED_TLS_ID} intersection goes all-red (ATTACK TRIGGERED)")
    logging.info(f"  Steps 120-359: Queue spillback cascades through network (post-attack)\n")
    
    # Run episode
    obs = env.reset()
    done = False
    step = 0
    
    while not done:
        # Take random actions (no policy)
        action_dict = {
            tls.id: env.action_space.sample()
            for tls in env.kernel.tls_hub
        }
        
        obs, reward, done, info = env.step(action_dict)
        
        # Get attacked TLS for logging
        attacked_tls = env.kernel.tls_hub[ATTACKED_TLS_ID]
        
        # Log every 60 steps + attack trigger
        if step % 60 == 0 or (step == ATTACK_TIMESTEP):
            occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
            avg_occupancy = sum(occupancies) / len(occupancies) if occupancies else 0
            
            if step == ATTACK_TIMESTEP:
                logging.info(f"\n[ATTACK TRIGGERED] Step {step}")
                logging.info(f"  Attacked TLS phase: {attacked_tls.state}")
                logging.info(f"  Attacked TLS occupancy: {obs[ATTACKED_TLS_ID][0]:.3f}")
                logging.info(f"  Under attack: {attacked_tls.is_under_attack}")
            
            logging.info(f"Step {step}: avg occupancy={avg_occupancy:.3f}, "
                        f"attacked_occupancy={obs[ATTACKED_TLS_ID][0]:.3f}, "
                        f"under_attack={attacked_tls.is_under_attack}")
        
        # Track results
        results["step"].append(step)
        results["attacked_phase"].append(attacked_tls.state)
        results["attacked_occupancy"].append(obs[ATTACKED_TLS_ID][0])
        results["attacked_halted_occupancy"].append(obs[ATTACKED_TLS_ID][1])
        results["attacked_under_attack"].append(attacked_tls.is_under_attack)
        
        occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
        results["center_total_occupancy"].append(sum(occupancies))
        results["network_avg_occupancy"].append(
            sum(occupancies) / len(occupancies) if occupancies else 0
        )
        
        step += 1
    
    # Save results
    df = pd.DataFrame(results)
    df.to_csv("cyberattack_test_results_gui.csv", index=False)
    logging.info("\nResults saved to cyberattack_test_results_gui.csv")
    
    # Print summary
    print("\n" + "="*80)
    print("CYBERATTACK TEST SUMMARY (GUI)")
    print("="*80 + "\n")
    
    pre_attack = df[df["step"] < ATTACK_TIMESTEP]
    post_attack = df[df["step"] >= ATTACK_TIMESTEP]
    
    print(f"Pre-Attack (steps 0-{ATTACK_TIMESTEP-1}):")
    print(f"  Avg network occupancy: {pre_attack['network_avg_occupancy'].mean():.4f}")
    print(f"  Avg attacked TLS occupancy: {pre_attack['attacked_occupancy'].mean():.4f}")
    
    print(f"\nPost-Attack (steps {ATTACK_TIMESTEP}-{HORIZON-1}):")
    print(f"  Avg network occupancy: {post_attack['network_avg_occupancy'].mean():.4f}")
    print(f"  Avg attacked TLS occupancy: {post_attack['attacked_occupancy'].mean():.4f}")
    print(f"  Avg attacked TLS halted occupancy: {post_attack['attacked_halted_occupancy'].mean():.4f}")
    print(f"  Under attack count: {post_attack['attacked_under_attack'].sum()} / {len(post_attack)} steps")
    
    occ_increase = (post_attack['network_avg_occupancy'].mean() - 
                    pre_attack['network_avg_occupancy'].mean())
    print(f"\nNetwork occupancy increase: +{occ_increase:.4f}")
    print("="*80)

if __name__ == "__main__":
    run_test_gui()
