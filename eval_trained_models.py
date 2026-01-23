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
import random
import ray
from pathlib import Path
from netfiles import GRID_3x3
from seal.sumo.env import SumoEnv
from seal.logging import logging
from seal.trainer.util import GLOBAL_POLICY_VAR, eval_policy_mapping_fn
from ray.rllib.agents.ppo import PPOTrainer

# SET GLOBAL SEED FOR REPRODUCIBILITY
# This ensures deterministic results across runs
np.random.seed(42)
random.seed(42)
os.environ['PYTHONHASHSEED'] = '42'

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

# Multi-agent and single-agent model paths
MULTIAGENT_WEIGHTS_DIR = Path("out/SMARTCOMP/weights/MultiAgent/grid-3x3")
SINGLEAGENT_WEIGHTS_DIR = Path("out/SMARTCOMP/weights/SingleAgent/grid-3x3")

MULTIAGENT_SCENARIOS = {
    "multiagent": "Cyberattack_3x3_resilience_multiagent_ranked.pkl",
}

SINGLEAGENT_SCENARIOS = {
    "singleagent": "Cyberattack_3x3_resilience_singleagent_ranked.pkl",
}


def load_trained_policy(weights_pkl: str, env_config: dict) -> PPOTrainer:
    """
    Load trained policy weights and create a PPOTrainer with those weights.
    
    This reconstructs the RLlib policy environment based on eval.py pattern.
    
    Args:
        weights_pkl: Path to .pkl file containing trained weights
        env_config: Environment configuration dictionary
        
    Returns:
        PPOTrainer object with weights loaded and ready for inference
    """
    # Create a temporary environment to get TLS IDs and action/observation spaces
    temp_env = SumoEnv(env_config)
    tls_ids = [tls.id for tls in temp_env.kernel.tls_hub]
    
    # Set up multiagent configuration
    multiagent = {
        "policies": {idx: (None, temp_env.observation_space, temp_env.action_space, {})
                     for idx in tls_ids + [GLOBAL_POLICY_VAR]},
        "policy_mapping_fn": eval_policy_mapping_fn
    }
    
    # Create PPOTrainer with the environment
    trainer = PPOTrainer(env=SumoEnv, config={
        "env_config": env_config,
        "framework": "torch",
        "in_evaluation": True,
        "log_level": "ERROR",
        "lr": 0.001,
        "multiagent": multiagent,
        "num_gpus": 0,
        "num_workers": 0,
        "explore": False,
    })
    
    # Load the weights from pkl file
    try:
        with open(weights_pkl, "rb") as f:
            weights = pickle.load(f)
        
        # Apply weights to all policies (including GLOBAL_POLICY_VAR)
        for idx in tls_ids + [GLOBAL_POLICY_VAR]:
            trainer.get_policy(idx).set_weights(weights)
        
        logging.info(f"Successfully loaded and applied weights from {weights_pkl}")
        return trainer
    except Exception as e:
        logging.error(f"Failed to load weights from {weights_pkl}: {e}")
        return None


def evaluate_scenario(scenario_name: str, trainer: PPOTrainer, env_config: dict) -> dict:
    """
    Evaluate a trained policy scenario under cyberattack.
    
    Args:
        scenario_name: Name of scenario (baseline, degraded, resilient)
        trainer: PPOTrainer object with loaded weights
        env_config: Environment configuration dictionary
        
    Returns:
        Dictionary with metrics
    """
    
    if not trainer:
        logging.error(f"No trainer loaded for {scenario_name}")
        return {}
    
    logging.info(f"\n{'='*80}")
    logging.info(f"Evaluating: {scenario_name.upper()}")
    logging.info(f"{'='*80}")
    
    # Reset all random seeds before evaluation for reproducibility
    np.random.seed(42)
    random.seed(42)
    
    # Create environment for evaluation
    env = SumoEnv(config=env_config)
    
    # Results tracking
    results = {
        "step": [],
        "attacked_occupancy": [],
        "attacked_halted_occupancy": [],
        "attacked_under_attack": [],
        "network_avg_occupancy": [],
    }
    
    logging.info(f"Running episode with attack at step {ATTACK_TIMESTEP if env_config.get('attack_timestep') else 'DISABLED'}")
    
    # Run episode
    obs = env.reset()
    done = False
    step = 0
    
    while not done:
        # Get actions from trained policy using trainer.compute_action()
        action_dict = {}
        for agent_id, agent_obs in obs.items():
            # Use the trainer to compute action with the loaded policy
            # compute_action returns the action directly (not a tuple)
            action = trainer.compute_action(agent_obs, policy_id=agent_id)
            action_dict[agent_id] = action
        
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
        if step == ATTACK_TIMESTEP and env_config.get('attack_timestep') is not None:
            logging.info(f"\n[ATTACK TRIGGERED] Step {step}")
            logging.info(f"  Under attack: {info[ATTACKED_TLS_ID]['under_attack']}\n")
        
        if step % 60 == 0 and step > 0:
            logging.info(f"Step {step}: avg_occupancy={results['network_avg_occupancy'][-1]:.4f}, "
                        f"under_attack={info[ATTACKED_TLS_ID]['under_attack']}")
        
        step += 1
        done = done["__all__"]
    
    env.close()
    
    # Compute metrics based on attack timing
    df = pd.DataFrame(results)
    if env_config.get('attack_timestep') is not None:
        pre_attack = df[df["step"] < env_config.get('attack_timestep', 0)]
        post_attack = df[df["step"] >= env_config.get('attack_timestep', 0)]
    else:
        # For baseline (no attack), use first half vs second half
        pre_attack = df[df["step"] < len(df) // 2]
        post_attack = df[df["step"] >= len(df) // 2]
    
    metrics = {
        "scenario": scenario_name,
        "pre_occupancy": pre_attack['network_avg_occupancy'].mean() if len(pre_attack) > 0 else 0,
        "post_occupancy": post_attack['network_avg_occupancy'].mean() if len(post_attack) > 0 else 0,
        "occupancy_change": (post_attack['network_avg_occupancy'].mean() - pre_attack['network_avg_occupancy'].mean()) if len(pre_attack) > 0 and len(post_attack) > 0 else 0,
        "halted_vehicles_mean": post_attack['attacked_halted_occupancy'].mean() if len(post_attack) > 0 else 0,
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
        
        # Determine attack configuration based on scenario
        # Baseline: no attack (control)
        # Degraded/Resilient: with attack (treatment)
        if "baseline" in scenario_name.lower():
            attack_timestep = None
            attacked_tls_id = None
            attack_type = None
            logging.info("Baseline scenario: NO ATTACK (control condition)")
        else:
            attack_timestep = ATTACK_TIMESTEP
            attacked_tls_id = ATTACKED_TLS_ID
            attack_type = ATTACK_TYPE
            logging.info(f"Attack scenario: {ATTACK_TYPE} on {ATTACKED_TLS_ID} at step {ATTACK_TIMESTEP}")
        
        # Set up environment config for this scenario
        env_config = {
            "net-file": GRID_3x3,
            "horizon": HORIZON,
            "ranked": True,
            "rand_routes_on_reset": True,
            "use_dynamic_seed": False,
            "rand_route_args": {
                "vehicles_per_lane_per_hour": 150,
                "seed": 42
            },
            "attack_timestep": attack_timestep,
            "attacked_tls_id": attacked_tls_id,
            "attack_type": attack_type,
        }
        
        # Get the full path to the weights pkl file
        pkl_file = WEIGHTS_DIR / SCENARIOS[scenario_name]
        
        if not pkl_file.exists():
            logging.warning(f"Weights file not found: {pkl_file}")
            continue
        
        # Load policy with trained weights
        trainer = load_trained_policy(str(pkl_file), env_config)
        
        if trainer is None:
            logging.warning(f"Skipping {scenario_name} - could not load trainer")
            continue
        
        # Evaluate
        metrics = evaluate_scenario(scenario_name, trainer, env_config)
        
        if metrics:
            all_metrics.append(metrics)
            
            # Compute summary metrics
            pre_attack = np.mean(metrics['attacked_occupancy'][:ATTACK_TIMESTEP]) if ATTACK_TIMESTEP > 0 else np.mean(metrics['attacked_occupancy'])
            post_attack = np.mean(metrics['attacked_occupancy'][ATTACK_TIMESTEP:]) if ATTACK_TIMESTEP < len(metrics['attacked_occupancy']) else np.mean(metrics['attacked_occupancy'])
            occupancy_increase = ((post_attack - pre_attack) / pre_attack * 100) if pre_attack > 0 else 0
            
            # Print scenario results
            print(f"\n{scenario_name}:")
            print(f"  Pre-attack occupancy:  {pre_attack:.4f}")
            print(f"  Post-attack occupancy: {post_attack:.4f}")
            print(f"  Occupancy increase: +{occupancy_increase:.1f}%")
        
        # Stop Ray after each scenario to free resources
        if ray.is_initialized():
            ray.shutdown()
    
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
