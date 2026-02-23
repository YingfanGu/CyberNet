"""
Evaluation Script: Test Per-Episode Weights During Training

This script evaluates the per-episode weight snapshots saved during training.
It loads weights from each episode and tests them to show how policy performance
improves over training iterations.

Designed to analyze:
- How policy performance changes per episode
- When the policy becomes effective against attacks
- Training convergence and stability

Usage:
    python eval_training_episodes.py --scenario degraded --episodes 1-20
    python eval_training_episodes.py --scenario degraded --episodes 5,10,15,20
    python eval_training_episodes.py --scenario degraded --all-episodes
"""

import os
import pickle
import pandas as pd
import numpy as np
import random
import ray
import argparse
import glob
from pathlib import Path
from netfiles import GRID_3x3
from seal.sumo.env import SumoEnv
from seal.logging import logging
from seal.trainer.util import GLOBAL_POLICY_VAR, eval_policy_mapping_fn
from ray.rllib.agents.ppo import PPOTrainer

# SET GLOBAL SEED FOR REPRODUCIBILITY
np.random.seed(42)
random.seed(42)
os.environ['PYTHONHASHSEED'] = '42'

# Configuration
HORIZON = 360
ATTACK_TIMESTEP = 120
ATTACKED_TLS_ID = "C2"
ATTACK_TYPE = "all_red"

# Per-episode weights directory paths
EPISODE_WEIGHTS_DIRS = {
    "baseline": "out/SMARTCOMP/weight_episode/FedRL/grid-5x5/Cyberattack_5x5_resilience_baseline_naive_ranked",
    "degraded": "out/SMARTCOMP/weight_episode/FedRL/grid-5x5/Cyberattack_5x5_resilience_degraded_naive",
    "resilient": "out/SMARTCOMP/weight_episode/FedRL/grid-5x5/Cyberattack_5x5_resilience_resilient_trust_ranked",
    "multiagent": "out/SMARTCOMP/weight_episode/MultiAgent/grid-5x5/Cyberattack_5x5_resilience_multiagent",
    "singleagent": "out/SMARTCOMP/weight_episode/SingleAgent/grid-5x5/Cyberattack_5x5_resilience_singleagent",
}


def find_episode_weights(scenario: str, episode_num: int = None) -> list:
    """
    Find episode weight files for a scenario.
    
    Args:
        scenario: 'baseline', 'degraded', or 'resilient'
        episode_num: Specific episode number to find, or None for all
        
    Returns:
        List of (episode_num, file_path) tuples, sorted by episode number
    """
    if scenario not in EPISODE_WEIGHTS_DIRS:
        logging.error(f"Unknown scenario: {scenario}")
        return []
    
    weights_dir = EPISODE_WEIGHTS_DIRS[scenario]
    
    if not os.path.exists(weights_dir):
        logging.warning(f"Weights directory not found: {weights_dir}")
        return []
    
    # Find all .pkl files
    pkl_files = glob.glob(os.path.join(weights_dir, "*.pkl"))
    
    if not pkl_files:
        logging.warning(f"No .pkl files found in {weights_dir}")
        return []
    
    # Extract episode numbers and sort
    episodes = []
    for pkl_file in pkl_files:
        filename = os.path.basename(pkl_file)
        try:
            ep_num = int(filename.replace('.pkl', ''))
            if episode_num is None or ep_num == episode_num:
                episodes.append((ep_num, pkl_file))
        except ValueError:
            logging.debug(f"Skipping non-episode file: {filename}")
    
    # Sort by episode number
    episodes.sort(key=lambda x: x[0])
    
    return episodes


def load_trained_policy(weights_pkl: str, env_config: dict) -> PPOTrainer:
    """
    Load trained policy weights and create a PPOTrainer with those weights.
    
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
        
        # Apply weights to all policies
        for idx in tls_ids + [GLOBAL_POLICY_VAR]:
            trainer.get_policy(idx).set_weights(weights)
        
        logging.info(f"Loaded weights from {os.path.basename(weights_pkl)}")
        return trainer
    except Exception as e:
        logging.error(f"Failed to load weights from {weights_pkl}: {e}")
        return None


def evaluate_episode(episode_num: int, scenario: str, trainer: PPOTrainer, 
                    env_config: dict) -> dict:
    """
    Evaluate a policy from a specific training episode.
    
    Args:
        episode_num: Training episode number
        scenario: Scenario name
        trainer: PPOTrainer object with loaded weights
        env_config: Environment configuration
        
    Returns:
        Dictionary with metrics
    """
    
    if not trainer:
        logging.error(f"No trainer for episode {episode_num}")
        return {}
    
    # Reset random seeds before evaluation
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
    
    # Run episode
    obs = env.reset()
    done = False
    step = 0
    
    while not done:
        # Get actions from trained policy
        action_dict = {}
        for agent_id, agent_obs in obs.items():
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
        
        step += 1
        done = done["__all__"]
    
    env.close()
    
    # Compute metrics
    df = pd.DataFrame(results)
    if env_config.get('attack_timestep') is not None:
        pre_attack = df[df["step"] < env_config.get('attack_timestep', 0)]
        post_attack = df[df["step"] >= env_config.get('attack_timestep', 0)]
    else:
        # For baseline (no attack), use first half vs second half
        pre_attack = df[df["step"] < len(df) // 2]
        post_attack = df[df["step"] >= len(df) // 2]
    
    pre_occ = pre_attack['network_avg_occupancy'].mean() if len(pre_attack) > 0 else 0
    post_occ = post_attack['network_avg_occupancy'].mean() if len(post_attack) > 0 else 0
    occupancy_increase = ((post_occ - pre_occ) / pre_occ * 100) if pre_occ > 0 else 0
    
    metrics = {
        "episode": episode_num,
        "scenario": scenario,
        "pre_occupancy": pre_occ,
        "post_occupancy": post_occ,
        "occupancy_increase": post_occ - pre_occ,
        "occupancy_increase_pct": occupancy_increase,
        "halted_vehicles_mean": post_attack['attacked_halted_occupancy'].mean() if len(post_attack) > 0 else 0,
    }
    
    return metrics


def parse_episode_range(episode_str: str, max_episode: int) -> list:
    """
    Parse episode range string into list of episode numbers.
    
    Examples:
        "1-5" -> [1, 2, 3, 4, 5]
        "5,10,15" -> [5, 10, 15]
        "all" -> [1, 2, ..., max_episode]
    """
    if episode_str.lower() == "all":
        return list(range(1, max_episode + 1))
    
    episodes = []
    
    # Handle comma-separated values
    if "," in episode_str:
        for part in episode_str.split(","):
            try:
                episodes.append(int(part.strip()))
            except ValueError:
                logging.warning(f"Invalid episode number: {part}")
    # Handle range (e.g., "1-5")
    elif "-" in episode_str:
        parts = episode_str.split("-")
        try:
            start = int(parts[0].strip())
            end = int(parts[1].strip())
            episodes.extend(range(start, end + 1))
        except (ValueError, IndexError):
            logging.warning(f"Invalid range format: {episode_str}")
    # Single episode
    else:
        try:
            episodes.append(int(episode_str.strip()))
        except ValueError:
            logging.warning(f"Invalid episode number: {episode_str}")
    
    return [ep for ep in episodes if 0 <= ep <= max_episode]


def main():
    """Run evaluation of per-episode weights."""
    
    parser = argparse.ArgumentParser(
        description="Evaluate per-episode weights during training"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="degraded",
        choices=["baseline", "degraded", "resilient"],
        help="Scenario to evaluate (default: degraded)"
    )
    parser.add_argument(
        "--episodes",
        type=str,
        default="all",
        help="Episodes to evaluate: '1-10' (range), '1,5,10' (specific), or 'all' (default: all)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV file (default: training_episodes_{scenario}.csv)"
    )
    
    args = parser.parse_args()
    
    scenario = args.scenario.lower()
    
    logging.info("="*100)
    logging.info(f"EVALUATING PER-EPISODE WEIGHTS - {scenario.upper()}")
    logging.info("="*100)
    
    # Find all available episodes for this scenario
    all_episodes = find_episode_weights(scenario)
    
    if not all_episodes:
        logging.error(f"No episode weights found for scenario: {scenario}")
        return
    
    max_episode = max([ep_num for ep_num, _ in all_episodes])
    logging.info(f"Found {len(all_episodes)} episodes (1 to {max_episode})")
    
    # Parse episode range
    episode_nums = parse_episode_range(args.episodes, max_episode)
    
    if not episode_nums:
        logging.error("No valid episodes to evaluate")
        return
    
    logging.info(f"Evaluating episodes: {episode_nums}")
    
    # Set up environment config
    if "baseline" in scenario.lower():
        attack_timestep = None
        attacked_tls_id = None
        attack_type = None
        logging.info("Baseline scenario: NO ATTACK (control)")
    else:
        attack_timestep = ATTACK_TIMESTEP
        attacked_tls_id = ATTACKED_TLS_ID
        attack_type = ATTACK_TYPE
        logging.info(f"Attack scenario: {attack_type} on {attacked_tls_id} at step {attack_timestep}")
    
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
    
    all_metrics = []
    
    # Evaluate each requested episode
    for episode_num in episode_nums:
        # Find the weights file for this episode
        weight_files = [f for f in all_episodes if f[0] == episode_num]
        
        if not weight_files:
            logging.warning(f"No weights found for episode {episode_num}, skipping")
            continue
        
        ep_num, weights_file = weight_files[0]
        
        logging.info(f"\n{'='*80}")
        logging.info(f"Episode {episode_num:06d}")
        logging.info(f"{'='*80}")
        
        # Load policy
        trainer = load_trained_policy(weights_file, env_config)
        
        if trainer is None:
            logging.warning(f"Skipping episode {episode_num}")
            continue
        
        # Evaluate
        metrics = evaluate_episode(episode_num, scenario, trainer, env_config)
        
        if metrics:
            all_metrics.append(metrics)
            print(f"\nEpisode {episode_num:06d}:")
            print(f"  Pre-attack occupancy:  {metrics['pre_occupancy']:.4f}")
            print(f"  Post-attack occupancy: {metrics['post_occupancy']:.4f}")
            print(f"  Occupancy increase:    +{metrics['occupancy_increase_pct']:.1f}%")
        
        # Free Ray resources
        if ray.is_initialized():
            ray.shutdown()
    
    # Print summary
    if all_metrics:
        print("\n" + "="*100)
        print(f"TRAINING PROGRESSION - {scenario.upper()}")
        print("="*100 + "\n")
        
        print(f"{'Episode':<12} {'Pre-Attack':<15} {'Post-Attack':<15} {'Increase':<15} {'Increase %':<15}")
        print("-" * 100)
        
        for metrics in all_metrics:
            ep = metrics['episode']
            pre = metrics['pre_occupancy']
            post = metrics['post_occupancy']
            inc = metrics['occupancy_increase']
            inc_pct = metrics['occupancy_increase_pct']
            
            print(f"{ep:<12} {pre:<15.4f} {post:<15.4f} {inc:<15.4f} {inc_pct:<15.1f}%")
        
        # Find best episode
        best_metrics = min(all_metrics, key=lambda x: x['occupancy_increase_pct'])
        worst_metrics = max(all_metrics, key=lambda x: x['occupancy_increase_pct'])
        
        print("\n" + "="*100)
        print("SUMMARY")
        print("="*100)
        print(f"\nBest episode: {best_metrics['episode']} with {best_metrics['occupancy_increase_pct']:.1f}% increase")
        print(f"Worst episode: {worst_metrics['episode']} with {worst_metrics['occupancy_increase_pct']:.1f}% increase")
        
        avg_increase = np.mean([m['occupancy_increase_pct'] for m in all_metrics])
        print(f"Average increase: {avg_increase:.1f}%")
        
        # Save results
        output_file = args.output or f"training_episodes_{scenario}.csv"
        df_results = pd.DataFrame(all_metrics)
        df_results.to_csv(output_file, index=False)
        logging.info(f"\nResults saved to {output_file}")
        
        print("\n" + "="*100)


if __name__ == "__main__":
    main()






'''
# All episodes
python eval_training_episodes.py --scenario degraded --episodes all

# Episode range (1-10)
python eval_training_episodes.py --scenario degraded --episodes 1-10

# Specific episodes
python eval_training_episodes.py --scenario degraded --episodes 1,5,10,15,20




'''