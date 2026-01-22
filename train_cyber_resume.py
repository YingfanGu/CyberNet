"""
Resume Cyberattack Training from Checkpoint

This script resumes training from the latest checkpoint saved during previous runs.
It loads the checkpoint and continues training for additional episodes.

Usage:
    python resume_training.py --episodes 35
    
This will continue training from the latest checkpoint for 35 more episodes.
"""

import os
import sys
from pathlib import Path
from netfiles import *
from seal.logging import *
from seal.trainer.fed_agent import FedPolicyTrainer
from seal.trainer.multi_agent import MultiPolicyTrainer
from seal.trainer.single_agent import SinglePolicyTrainer
from os.path import join
import argparse

# Set environment variable to suppress Ray's argparse
os.environ['RAY_DISABLE_MEMORY_MONITOR'] = '1'

# Set SUMO_HOME environment variable
# os.environ['SUMO_HOME'] = r'C:\Program Files (x86)\Eclipse\Sumo'

# Cyberattack scenarios
OUT_PREFIX = "Cyberattack_3x3_resilience"
random_routes_config = {}
trainer_kwargs = {
    "horizon": 360,  # 360 steps = 6 minutes
    # "timesteps_per_iteration":  240,
    # "batch_mode": "truncate_episodes",
    # "rollout_fragment_length": 240,
    # "train_batch_size": 240,

    # ====================== #
    # PPO Trainer Arguments. #
    # ====================== #
    # "sgd_minibatch_size": 30,
}

# Cyberattack parameters
ATTACK_TIMESTEP = 120  # Attack after 2 minutes (step 120)
ATTACKED_TLS_ID = "B1"  # Center intersection in 3x3 grid
ATTACK_TYPE = "all_red"  # All-red phase lock attack


def find_latest_checkpoint(scenario_name):
    """
    Find the latest checkpoint for a given scenario.
    Prioritizes clean checkpoints (.pkl files) over old Ray checkpoints.
    
    Args:
        scenario_name: 'baseline', 'degraded', or 'resilient'
    
    Returns:
        Path to latest checkpoint, or None if not found
    """
    base_checkpoint_dir = f"out/SMARTCOMP/checkpoints/FedRL/grid-3x3"
    
    if not os.path.exists(base_checkpoint_dir):
        logging.warning(f"Checkpoint directory not found: {base_checkpoint_dir}")
        return None
    
    # Map scenario names to folder patterns
    scenario_patterns = {
        "baseline": "baseline_naive",
        "degraded": "degraded_naive", 
        "resilient": "resilient_trust"
    }
    
    pattern = scenario_patterns.get(scenario_name.lower(), scenario_name.lower())
    logging.info(f"Looking for checkpoints matching pattern: *{pattern}*")
    
    # First, look for CLEAN CHECKPOINTS (.pkl files)
    clean_checkpoints = []
    for root, dirs, files in os.walk(base_checkpoint_dir):
        # Check if this folder contains the scenario pattern
        if pattern in root.lower():
            for file in files:
                if file.endswith('.pkl') and file.startswith('checkpoint_'):
                    # Extract checkpoint number from filename
                    try:
                        checkpoint_num = int(file.replace('checkpoint_', '').replace('.pkl', ''))
                        clean_checkpoints.append((checkpoint_num, root))
                        logging.debug(f"Found clean checkpoint: {file} in {root}")
                    except ValueError:
                        pass
    
    # If we found clean checkpoints, use the latest one
    if clean_checkpoints:
        clean_checkpoints.sort(reverse=True)  # Sort by checkpoint number, descending
        latest_num, checkpoint_dir = clean_checkpoints[0]
        checkpoint_file = os.path.join(checkpoint_dir, f"checkpoint_{latest_num:06d}.pkl")
        logging.info(f"Found clean checkpoints! Using latest: checkpoint_{latest_num:06d}.pkl in {checkpoint_dir}")
        # Normalize path to use forward slashes
        checkpoint_file = checkpoint_file.replace("\\", "/")
        logging.info(f"Selected latest checkpoint for '{scenario_name}' (#{latest_num}): {checkpoint_file}")
        return checkpoint_file
    
    # Fallback: look for old Ray checkpoint directories
    logging.info("No clean checkpoints found, falling back to old Ray checkpoints...")
    ray_checkpoints = []
    for root, dirs, files in os.walk(base_checkpoint_dir):
        # Check if this folder contains the scenario pattern
        if pattern in root.lower():
            for item in dirs:
                if item.startswith("checkpoint_"):
                    checkpoint_path = os.path.join(root, item)
                    if os.path.isdir(checkpoint_path):
                        ray_checkpoints.append(checkpoint_path)
                        logging.debug(f"Found Ray checkpoint: {checkpoint_path}")
    
    if not ray_checkpoints:
        logging.warning(f"No checkpoints found for scenario '{scenario_name}' (pattern: {pattern})")
        logging.info(f"Available directories in {base_checkpoint_dir}:")
        for item in os.listdir(base_checkpoint_dir):
            item_path = os.path.join(base_checkpoint_dir, item)
            if os.path.isdir(item_path):
                logging.info(f"  - {item}")
        return None
    
    # Sort by checkpoint number (extracted from folder name)
    # e.g., "checkpoint_000050" → 50
    def get_checkpoint_number(checkpoint_path):
        folder_name = os.path.basename(checkpoint_path)
        try:
            number = int(folder_name.split("_")[-1])
            return number
        except (ValueError, IndexError):
            # Fallback to modification time if parsing fails
            return os.path.getmtime(checkpoint_path)
    
    # Get the checkpoint with the highest number
    latest_checkpoint = max(ray_checkpoints, key=get_checkpoint_number)
    checkpoint_num = get_checkpoint_number(latest_checkpoint)
    
    # Normalize path to use forward slashes (Ray compatibility)
    latest_checkpoint = latest_checkpoint.replace("\\", "/")
    
    logging.warning(f"Using old Ray checkpoint (may have compatibility issues)")
    logging.info(f"Selected latest checkpoint for '{scenario_name}' (#{checkpoint_num}): {latest_checkpoint}")
    return latest_checkpoint


def resume_baseline(net_file, ranked, n_episodes, fed_step, checkpoint):
    """Resume baseline scenario training from checkpoint."""
    logging.info("\n" + "="*80)
    logging.info("RESUMING BASELINE SCENARIO TRAINING")
    logging.info(f"Checkpoint: {checkpoint}")
    logging.info(f"Additional episodes: {n_episodes}")
    logging.info("="*80 + "\n")
    
    logging.info("Resuming FedPolicyTrainer (aggr='naive') - BASELINE")
    baseline_prefix = f"{OUT_PREFIX}_baseline_naive_resume"  # _resume suffix to distinguish from initial training
    
    class BaselineTrainer(FedPolicyTrainer):
        def env_config_fn(self):
            config = super().env_config_fn()
            config["attack_timestep"] = None
            config["attacked_tls_id"] = None
            config["use_trust_scoring"] = False
            config["use_dynamic_seed"] = False  # Fixed seed for reproducibility
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150,
                "seed": 42
            }
            return config
    
    trainer = BaselineTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=baseline_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="naive",
        checkpoint_freq=1,  # Match train_cyberattack.py baseline config
    )
    
    # Ray's restore expects the checkpoint directory itself
    # checkpoint variable already contains the full path to checkpoint_000003
    # Just normalize it to use forward slashes
    checkpoint_dir = checkpoint.replace("\\", "/")
    
    # Train from checkpoint
    trainer.train(n_episodes, checkpoint=checkpoint_dir)


def resume_degraded(net_file, ranked, n_episodes, fed_step, checkpoint):
    """Resume degraded scenario training from checkpoint."""
    logging.info("\n" + "="*80)
    logging.info("RESUMING DEGRADED SCENARIO TRAINING")
    logging.info(f"Checkpoint: {checkpoint}")
    logging.info(f"Additional episodes: {n_episodes}")
    logging.info("="*80 + "\n")
    
    logging.info("Resuming FedPolicyTrainer (aggr='naive') - DEGRADED")
    degraded_prefix = f"{OUT_PREFIX}_degraded_naive_resume"  # _resume suffix to distinguish from initial training
    
    class DegradedTrainer(FedPolicyTrainer):
        def env_config_fn(self):
            config = super().env_config_fn()
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            config["use_trust_scoring"] = False
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150,
                "seed": 42
            }
            return config
    
    trainer = DegradedTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=degraded_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="naive",
        checkpoint_freq=1,  # Match train_cyberattack.py degraded config
    )
    
    # Ray's restore expects the checkpoint directory itself
    # checkpoint variable already contains the full path to checkpoint_000003
    # Just normalize it to use forward slashes
    checkpoint_dir = checkpoint.replace("\\", "/")
    
    # Train from checkpoint
    trainer.train(n_episodes, checkpoint=checkpoint_dir)


def resume_resilient(net_file, ranked, n_episodes, fed_step, checkpoint):
    """Resume resilient scenario training from checkpoint."""
    logging.info("\n" + "="*80)
    logging.info("RESUMING RESILIENT SCENARIO TRAINING")
    logging.info(f"Checkpoint: {checkpoint}")
    logging.info(f"Additional episodes: {n_episodes}")
    logging.info("="*80 + "\n")
    
    logging.info("Resuming FedPolicyTrainer (aggr='trust') - RESILIENT")
    resilient_prefix = f"{OUT_PREFIX}_resilient_trust_resume"  # _resume suffix to distinguish from initial training
    
    class ResilientTrainer(FedPolicyTrainer):
        def env_config_fn(self):
            config = super().env_config_fn()
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            config["use_trust_scoring"] = True
            config["trust_window_size"] = 20
            config["trust_spillback_threshold"] = 0.15
            config["trust_phase_lock_threshold"] = 30
            config["trust_ema_alpha"] = 0.1
            config["trust_suspected_threshold"] = 0.5
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150
            }
            return config
    
    trainer = ResilientTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=resilient_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="trust",
        checkpoint_freq=1,  # Match train_cyberattack.py resilient config
    )
    
    # Ray's restore expects the checkpoint directory itself
    # checkpoint variable already contains the full path to checkpoint_000003
    # Just normalize it to use forward slashes
    checkpoint_dir = checkpoint.replace("\\", "/")
    
    # Train from checkpoint
    trainer.train(n_episodes, checkpoint=checkpoint_dir)


def main():
    # Save original argv before parsing
    original_argv = sys.argv.copy()
    
    parser = argparse.ArgumentParser(
        description="Resume cyberattack training from checkpoint"
    )
    parser.add_argument(
        "--episodes", 
        type=int, 
        default=35,
        help="Number of additional episodes to train (default: 35)"
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="Path to specific checkpoint to resume from (auto-finds latest if not specified)"
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        nargs="+",
        default=["baseline", "degraded", "resilient"],
        help="Which scenarios to train: baseline, degraded, resilient (default: all three)"
    )
    
    args = parser.parse_args()
    
    # Clear sys.argv to prevent trainer from trying to parse arguments
    # Set to empty list so argparse has no arguments to process
    sys.argv = [original_argv[0]]
    
    n_episodes = args.episodes
    fed_step = 1
    
    NET_FILES = {
        "grid_3x3": GRID_3x3,
    }
    
    RANKED = [True]
    
    logging.info("="*80)
    logging.info("RESUMING CYBERATTACK RESILIENCE TRAINING")
    logging.info(f"Additional episodes: {n_episodes}")
    logging.info(f"Scenarios: {', '.join(args.scenarios)}")
    logging.info("="*80)
    
    # Run experiments for each network and ranking configuration
    for (intersection, net_file) in NET_FILES.items():
        for ranked in RANKED:
            logging.info(f"\n{'='*80}")
            logging.info(f"Network: {intersection}, Ranked: {ranked}")
            logging.info(f"{'='*80}")
            
            if "baseline" in args.scenarios:
                logging.info("\n1. Resuming BASELINE")
                checkpoint = args.checkpoint if args.checkpoint else find_latest_checkpoint("baseline")
                if checkpoint:
                    resume_baseline(net_file, ranked, n_episodes, fed_step, checkpoint)
                else:
                    logging.error("Cannot resume baseline: no checkpoint found")
            
            if "degraded" in args.scenarios:
                logging.info("\n2. Resuming DEGRADED")
                checkpoint = args.checkpoint if args.checkpoint else find_latest_checkpoint("degraded")
                if checkpoint:
                    resume_degraded(net_file, ranked, n_episodes, fed_step, checkpoint)
                else:
                    logging.error("Cannot resume degraded: no checkpoint found")
            
            if "resilient" in args.scenarios:
                logging.info("\n3. Resuming RESILIENT")
                checkpoint = args.checkpoint if args.checkpoint else find_latest_checkpoint("resilient")
                if checkpoint:
                    resume_resilient(net_file, ranked, n_episodes, fed_step, checkpoint)
                else:
                    logging.error("Cannot resume resilient: no checkpoint found")
            
            logging.info(f"\nCompleted all scenarios for {intersection} (ranked={ranked})")
    
    logging.info("\n" + "="*80)
    logging.info("TRAINING RESUME COMPLETE")
    logging.info("Updated pkl files in example_weights/")
    logging.info("="*80)


if __name__ == "__main__":
    main()




'''
Usage:
Resume all three scenarios (recommended):

python rtrain_cyber_resume.py --episodes 48

Resume only resilient:

python train_cyber_resume.py --episodes 48 --scenarios resilient

Resume baseline and degraded only:

python train_cyber_resume.py --episodes 48 --scenarios baseline degraded
'''


