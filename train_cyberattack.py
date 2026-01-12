"""
Federated Traffic Control Training Under Cyberattack Scenarios.

This script extends train.py to include cyberattack scenarios:
1. BASELINE: No attack (normal operation, for comparison)
2. DEGRADED: Cyberattack on center intersection (all-red phase lock)
3. RESILIENT: Cyberattack + Trust-weighted aggregation defense

Trains federated RL agents to handle traffic control under attack.

Refer to original train.py for base pipeline.
"""
import os
from netfiles import *
from seal.logging import *
from seal.trainer.fed_agent import FedPolicyTrainer
from seal.trainer.multi_agent import MultiPolicyTrainer
from seal.trainer.single_agent import SinglePolicyTrainer
from os.path import join

# Set SUMO_HOME environment variable
# os.environ['SUMO_HOME'] = r'C:\Program Files (x86)\Eclipse\Sumo'

# Cyberattack scenarios
OUT_PREFIX = "Cyberattack_3x3_resilience"
random_routes_config = {}
trainer_kwargs = {
    # =========================================================== #
    # Non-Algorithm Trainer Arguments (i.e., not related to PPO). #
    # =========================================================== #
    "horizon": 360,  # 360 steps = 6 minutes
    "simple_optimizer": True,  # Add this line
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


def train_baseline(net_file, ranked, n_episodes, fed_step):
    """
    Train baseline scenario: No cyberattack, normal operation.
    This is the control/comparison scenario.
    """
    logging.info("\n" + "="*80)
    logging.info("BASELINE SCENARIO: Normal Traffic Control (No Attack)")
    logging.info("="*80 + "\n")
    
    # Baseline: pos_reward aggregation, no attack
    logging.info("Training FedPolicyTrainer (aggr='pos_reward') - BASELINE")
    baseline_prefix = f"{OUT_PREFIX}_baseline_pos-reward"
    FedPolicyTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=baseline_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="pos_reward",
        # log_level="INFO"
    ).train(n_episodes)
    
    # Baseline: naive aggregation, no attack
    logging.info("Training FedPolicyTrainer (aggr='naive') - BASELINE")
    baseline_prefix = f"{OUT_PREFIX}_baseline_naive"
    FedPolicyTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=baseline_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="naive",
        # log_level="INFO"
    ).train(n_episodes)


def train_degraded(net_file, ranked, n_episodes, fed_step):
    """
    Train degraded scenario: Cyberattack on center intersection, no defense.
    Shows impact of undefended cyberattack on federated learning.
    
    NOTE: Attack integration requires environment-level config support in BaseTrainer.
    Current limitation: Using baseline training as placeholder for degraded scenario.
    Future work: Extend BaseTrainer to pass env_config separately from trainer_kwargs.
    """
    logging.info("\n" + "="*80)
    logging.info("DEGRADED SCENARIO: Cyberattack Without Defense (PLACEHOLDER)")
    logging.info(f"Attack Config: {ATTACK_TYPE} on {ATTACKED_TLS_ID} at step {ATTACK_TIMESTEP}")
    logging.info("NOTE: Full attack integration pending (see test_cyberattack.py for working example)")
    logging.info("="*80 + "\n")
    
    # TODO: Implement environment config passing in BaseTrainer
    # For now, run degraded scenario as baseline (no attack)
    # Real implementation would pass attack_timestep, attacked_tls_id, attack_type
    
    # Degraded: pos_reward with attack, no trust defense
    logging.info("Training FedPolicyTrainer (aggr='pos_reward') - DEGRADED (placeholder)")
    degraded_prefix = f"{OUT_PREFIX}_degraded_pos-reward"
    FedPolicyTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=degraded_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="pos_reward",
        # log_level="INFO"
    ).train(n_episodes)
    
    # Degraded: naive with attack, no trust defense
    logging.info("Training FedPolicyTrainer (aggr='naive') - DEGRADED (placeholder)")
    degraded_prefix = f"{OUT_PREFIX}_degraded_naive"
    FedPolicyTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=degraded_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="naive",
        # log_level="INFO"
    ).train(n_episodes)


def train_resilient(net_file, ranked, n_episodes, fed_step):
    """
    Train resilient scenario: Cyberattack with trust-weighted aggregation defense.
    Trust-weighted FedAvg reduces impact of compromised agent.
    
    NOTE: Attack integration requires environment-level config support in BaseTrainer.
    Current limitation: Using trust-weighted aggregation without active attack.
    Future work: Extend BaseTrainer to pass env_config separately from trainer_kwargs.
    """
    logging.info("\n" + "="*80)
    logging.info("RESILIENT SCENARIO: Trust-Weighted Defense (NO ACTIVE ATTACK)")
    logging.info(f"Attack Config (for future): {ATTACK_TYPE} on {ATTACKED_TLS_ID} at step {ATTACK_TIMESTEP}")
    logging.info("Defense: Trust-weighted federated aggregation")
    logging.info("="*80 + "\n")
    
    # TODO: Implement environment config passing in BaseTrainer
    # For now, demonstrate trust-weighted aggregation without active attack
    # Real implementation would pass attack_timestep, attacked_tls_id, attack_type
    
    # Resilient: trust-weighted aggregation (no active attack yet)
    logging.info("Training FedPolicyTrainer (aggr='trust') - RESILIENT (trust-weighted, no active attack)")
    resilient_prefix = f"{OUT_PREFIX}_resilient_trust"
    FedPolicyTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=resilient_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="trust",  # Trust-weighted defense
        # log_level="INFO"
    ).train(n_episodes)


if __name__ == "__main__":
    n_episodes = 2  # Number of training episodes
    fed_step = 1    # Aggregation frequency
    
    NET_FILES = {
        "grid_3x3": GRID_3x3,
        # Uncomment to test on larger networks
        # "grid_5x5": GRID_5x5,
        # "grid_7x7": GRID_7x7
    }
    
    RANKED = [True]  # Set to True or [True, False] for both
    
    logging.info("="*80)
    logging.info("CYBERATTACK RESILIENCE TRAINING")
    logging.info("Comparing: Baseline vs Degraded vs Resilient scenarios")
    logging.info("="*80)
    
    # Run experiments for each network and ranking configuration
    for (intersection, net_file) in NET_FILES.items():
        for ranked in RANKED:
            logging.info(f"\n{'='*80}")
            logging.info(f"Network: {intersection}, Ranked: {ranked}")
            logging.info(f"{'='*80}")
            
            # 1. BASELINE: Normal operation (control scenario)
            train_baseline(net_file, ranked, n_episodes, fed_step)
            
            # 2. DEGRADED: Attack without defense (vulnerability scenario)
            train_degraded(net_file, ranked, n_episodes, fed_step)
            
            # 3. RESILIENT: Attack with trust-based defense (resilience scenario)
            train_resilient(net_file, ranked, n_episodes, fed_step)
            
            logging.info(f"\nCompleted all scenarios for {intersection} (ranked={ranked})")
    
    logging.info("\n" + "="*80)
    logging.info("TRAINING COMPLETE")
    logging.info("Generated outputs in example_weights/")
    logging.info("="*80)
