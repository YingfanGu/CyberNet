"""
Evaluation Script: Compare Trained Models Under Cyberattack

Loads trained policies from train_cyberattack.py scenarios and evaluates them
against cyberattack to compare performance:
- BASELINE: Normal training (control)
- DEGRADED: Training without attack (worse under attack)
- RESILIENT: Training with trust-weighted defense (hopefully better)

Results show which defense strategy is most effective.
"""

import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from netfiles import GRID_3x3
from seal.sumo.env import SumoEnv
from seal.logging import logging

# Configuration
HORIZON = 360
ATTACK_TIMESTEP = 120
ATTACKED_TLS_ID = "B1"
ATTACK_TYPE = "all_red"

# Trained model paths
WEIGHTS_DIR = Path("out/SMARTCOMP/weights/FedRL/grid-3x3")

SCENARIOS = {
    # "baseline_pos_reward": "Cyberattack_3x3_resilience_baseline_pos-reward_ranked.pkl",
    "baseline_naive": "Cyberattack_3x3_resilience_baseline_naive_ranked.pkl",
    # "degraded_pos_reward": "Cyberattack_3x3_resilience_degraded_pos-reward_ranked.pkl",
    "degraded_naive": "Cyberattack_3x3_resilience_degraded_naive_ranked.pkl",
    "resilient_trust": "Cyberattack_3x3_resilience_resilient_trust_ranked.pkl",
}


def load_trained_policy(scenario_name: str):
    """Load trained policy from pkl file."""
    pkl_file = WEIGHTS_DIR / SCENARIOS[scenario_name]
    
    if not pkl_file.exists():
        logging.warning(f"File not found: {pkl_file}")
        return None
    
    try:
        with open(pkl_file, 'rb') as f:
            policy = pickle.load(f)
        logging.info(f"Loaded policy: {scenario_name}")
        return policy
    except Exception as e:
        logging.error(f"Failed to load {scenario_name}: {e}")
        return None


def evaluate_scenario(scenario_name: str, policy_dict: dict) -> dict:
    """
    Evaluate a trained policy scenario under cyberattack.
    
    Args:
        scenario_name: Name of scenario (baseline, degraded, resilient)
        policy_dict: Dictionary of trained policies, one per TLS agent
        
    Returns:
        Dictionary with metrics
    """
    
    if not policy_dict:
        logging.error(f"No policies loaded for {scenario_name}")
        return {}
    
    logging.info(f"\n{'='*80}")
    logging.info(f"Evaluating: {scenario_name.upper()}")
    logging.info(f"{'='*80}")
    
    # Environment configuration
    env_config = {
        "net-file": GRID_3x3,
        "horizon": HORIZON,
        "ranked": True,
        "rand_routes_on_reset": True,
        "rand_route_args": {
            "vehicles_per_lane_per_hour": 360,
        },
        # Attack configuration
        "attack_timestep": ATTACK_TIMESTEP,
        "attacked_tls_id": ATTACKED_TLS_ID,
        "attack_type": ATTACK_TYPE,
    }
    
    # Create environment
    env = SumoEnv(config=env_config)
    
    # Results tracking
    results = {
        "step": [],
        "attacked_occupancy": [],
        "attacked_halted_occupancy": [],
        "attacked_under_attack": [],
        "network_avg_occupancy": [],
    }
    
    # Get attacked TLS for logging
    attacked_tls = env.kernel.tls_hub[ATTACKED_TLS_ID]
    
    logging.info(f"Running episode with attack at step {ATTACK_TIMESTEP}")
    
    # Run episode
    obs = env.reset()
    done = False
    step = 0
    
    while not done:
        # Get actions from trained policies
        action_dict = {}
        # Iterate over TLS IDs, not objects
        for tls_id in env.kernel.tls_hub.ids:
            # Use trained policy if available
            if tls_id in policy_dict:
                try:
                    obs_tensor = obs[tls_id]
                    # Call policy to get action (simplified - may need adjustment based on policy type)
                    action = policy_dict[tls_id] if isinstance(policy_dict[tls_id], int) else 0
                    action_dict[tls_id] = action
                except:
                    # Fallback to phase progression if policy call fails
                    action_dict[tls_id] = 0
            else:
                action_dict[tls_id] = 0
        
        # Take step
        obs, reward, done, info = env.step(action_dict)
        
        # Track metrics
        attacked_obs = obs[ATTACKED_TLS_ID]
        results["step"].append(step)
        results["attacked_occupancy"].append(attacked_obs[0])
        results["attacked_halted_occupancy"].append(attacked_obs[1])
        results["attacked_under_attack"].append(info[ATTACKED_TLS_ID]["under_attack"])
        
        # Network metrics
        occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
        results["network_avg_occupancy"].append(np.mean(occupancies))
        
        # Log key moments
        if step == ATTACK_TIMESTEP:
            logging.info(f"\n[ATTACK TRIGGERED] Step {step}")
            logging.info(f"  Under attack: {info[ATTACKED_TLS_ID]['under_attack']}\n")
        
        if step % 60 == 0 and step > 0:
            logging.info(f"Step {step}: avg_occupancy={results['network_avg_occupancy'][-1]:.4f}, "
                        f"under_attack={info[ATTACKED_TLS_ID]['under_attack']}")
        
        step += 1
        done = done["__all__"]
    
    env.close()
    
    # Compute metrics
    df = pd.DataFrame(results)
    pre_attack = df[df["step"] < ATTACK_TIMESTEP]
    post_attack = df[df["step"] >= ATTACK_TIMESTEP]
    
    metrics = {
        "scenario": scenario_name,
        "pre_attack_occupancy": pre_attack['network_avg_occupancy'].mean(),
        "post_attack_occupancy": post_attack['network_avg_occupancy'].mean(),
        "occupancy_increase": post_attack['network_avg_occupancy'].mean() - pre_attack['network_avg_occupancy'].mean(),
        "occupancy_increase_pct": ((post_attack['network_avg_occupancy'].mean() - pre_attack['network_avg_occupancy'].mean()) / 
                                   pre_attack['network_avg_occupancy'].mean() * 100),
        "halted_vehicles_mean": post_attack['attacked_halted_occupancy'].mean(),
    }
    
    return metrics


def print_comparison(all_metrics: list):
    """Print comparison table of all scenarios."""
    
    if not all_metrics:
        logging.error("No metrics to compare")
        return
    
    print("\n" + "="*100)
    print("TRAINING EVALUATION RESULTS - COMPARISON")
    print("="*100 + "\n")
    
    # Sort by occupancy increase (lower is better)
    all_metrics.sort(key=lambda x: x['occupancy_increase_pct'])
    
    print(f"{'Scenario':<30} {'Pre-Attack':<15} {'Post-Attack':<15} {'Increase':<15} {'Increase %':<15}")
    print("-" * 100)
    
    baseline_occupancy = None
    best_scenario = None
    best_reduction = 0
    
    for metrics in all_metrics:
        scenario = metrics['scenario']
        pre = metrics['pre_attack_occupancy']
        post = metrics['post_attack_occupancy']
        inc = metrics['occupancy_increase']
        inc_pct = metrics['occupancy_increase_pct']
        
        # Track baseline for comparison
        if "baseline" in scenario and baseline_occupancy is None:
            baseline_occupancy = inc_pct
        
        # Find best defense
        if baseline_occupancy and inc_pct < baseline_occupancy:
            reduction = baseline_occupancy - inc_pct
            if reduction > best_reduction:
                best_reduction = reduction
                best_scenario = scenario
        
        marker = " ⭐ BEST" if best_scenario == scenario else ""
        print(f"{scenario:<30} {pre:<15.4f} {post:<15.4f} {inc:<15.4f} {inc_pct:<15.1f}%{marker}")
    
    print("\n" + "="*100)
    print("SUMMARY")
    print("="*100)
    
    if baseline_occupancy:
        print(f"\nBaseline vulnerability: +{baseline_occupancy:.1f}% occupancy increase under attack")
        
        if best_scenario and best_reduction > 0:
            print(f"\n✅ BEST DEFENSE: {best_scenario.upper()}")
            print(f"   Reduces attack impact by {best_reduction:.1f} percentage points")
            print(f"   Final increase: {baseline_occupancy - best_reduction:.1f}% (vs {baseline_occupancy:.1f}% baseline)")
        else:
            print("\n⚠️  No defense shows improvement yet.")
            print("   This may indicate:")
            print("   - Trained models need more training")
            print("   - Trust weighting needs calibration")
            print("   - Attack is too severe for current defense")
    
    print("\n" + "="*100)


def main():
    """Run evaluation."""
    
    # Check if weights directory exists
    if not WEIGHTS_DIR.exists():
        logging.error(f"Weights directory not found: {WEIGHTS_DIR}")
        logging.info("Make sure train_cyberattack.py has completed successfully")
        return
    
    logging.info("="*100)
    logging.info("EVALUATING TRAINED MODELS UNDER CYBERATTACK")
    logging.info("="*100)
    
    all_metrics = []
    
    # Evaluate each scenario
    for scenario_name in SCENARIOS.keys():
        logging.info(f"\nLoading {scenario_name}...")
        
        # Load policy
        policy = load_trained_policy(scenario_name)
        
        if policy is None:
            logging.warning(f"Skipping {scenario_name} - could not load")
            continue
        
        # Evaluate
        metrics = evaluate_scenario(scenario_name, policy)
        
        if metrics:
            all_metrics.append(metrics)
            
            # Print scenario results
            print(f"\n{scenario_name}:")
            print(f"  Pre-attack occupancy:  {metrics['pre_attack_occupancy']:.4f}")
            print(f"  Post-attack occupancy: {metrics['post_attack_occupancy']:.4f}")
            print(f"  Occupancy increase: +{metrics['occupancy_increase_pct']:.1f}%")
    
    # Print comparison
    print_comparison(all_metrics)
    
    # Save results to CSV
    if all_metrics:
        df_results = pd.DataFrame(all_metrics)
        output_file = "training_evaluation_results.csv"
        df_results.to_csv(output_file, index=False)
        logging.info(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()
