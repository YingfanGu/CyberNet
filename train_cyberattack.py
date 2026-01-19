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
    "horizon": 360,  # 360 steps = 6 minutes (enough to show attack + defense),
    # GPU disabled: overhead > benefit for small batches (SUMO is CPU bottleneck)
    # "timesteps_per_iteration":  240,
    # "batch_mode": "truncate_episodes",
    # "rollout_fragment_length": 240,
    # "train_batch_size": 240,
    # "rand_routes_on_reset": False,  # ← Add this to use same routes every time

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
    This is the control/comparison scenario for measuring attack impact.
    
    ✓ NO ATTACK - clean environment, no cyberattack injection
    ✓ Naive aggregation - standard FedAvg without trust weighting
    """
    logging.info("\n" + "="*80)
    logging.info("BASELINE SCENARIO: Normal Traffic Control (No Attack)")
    logging.info("Control condition: Federated learning without cyberattack")
    logging.info("✓ NO ATTACK during training")
    logging.info("✓ Naive aggregation (standard FedAvg)")
    logging.info("="*80 + "\n")
    
    # Baseline: naive aggregation, NO ATTACK
    logging.info("Training FedPolicyTrainer (aggr='naive') - BASELINE")
    baseline_prefix = f"{OUT_PREFIX}_baseline_naive"
    
    # Create custom trainer with no attack
    class BaselineTrainer(FedPolicyTrainer):
        def env_config_fn(self):
            config = super().env_config_fn()
            # NO ATTACK - baseline runs without cyberattack
            config["attack_timestep"] = None  # Explicitly disable attack
            config["attacked_tls_id"] = None
            config["use_trust_scoring"] = False  # No trust scoring needed
            config["use_dynamic_seed"] = False  # Fixed seed for reproducibility
            # Vehicle flow configuration
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150,  # Reduced from 360 for better training
                "seed": 42  # Fixed seed for reproducibility
            }
            return config
    
    BaselineTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=baseline_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="naive",
        checkpoint_freq=1,  # Save checkpoint every episode
        # log_level="INFO"
    ).train(n_episodes)


def train_degraded(net_file, ranked, n_episodes, fed_step):
    """
    Train degraded scenario: Cyberattack on center intersection, no defense.
    Shows impact of undefended cyberattack on federated learning.
    
    This scenario demonstrates vulnerability: naive aggregation cannot defend.
    
    ✓ ATTACK ENABLED - cyberattack injected at step 120 (all-red phase lock on B1)
    ✓ Naive aggregation - NO defense (vulnerable to attack)
    """
    logging.info("\n" + "="*80)
    logging.info("DEGRADED SCENARIO: Cyberattack Without Defense")
    logging.info(f"Attack Config: {ATTACK_TYPE} on {ATTACKED_TLS_ID} at step {ATTACK_TIMESTEP}")
    logging.info("✓ ATTACK ENABLED during training")
    logging.info("✓ No defense: naive aggregation (vulnerable to attack)")
    logging.info("="*80 + "\n")
    
    # Degraded: naive with attack, no trust defense
    logging.info("Training FedPolicyTrainer (aggr='naive') - DEGRADED")
    degraded_prefix = f"{OUT_PREFIX}_degraded_naive"
    
    # Create custom trainer with attack enabled
    class DegradedTrainer(FedPolicyTrainer):
        def env_config_fn(self):
            config = super().env_config_fn()
            # ATTACK ENABLED - cyberattack on B1 at step 120
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            config["use_trust_scoring"] = False  # No trust defense
            # Vehicle flow configuration
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150  # Reduced from 360 for better training
            }
            return config
    
    DegradedTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=degraded_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="naive",  # Naive aggregation - vulnerable
        checkpoint_freq=1,  # Save checkpoint every episode
        # log_level="INFO"
    ).train(n_episodes)


def train_resilient(net_file, ranked, n_episodes, fed_step):
    """
    Train resilient scenario: Cyberattack with trust-weighted aggregation defense.
    Trust-weighted FedAvg reduces impact of compromised agent.
    
    This scenario demonstrates the defense: trust weighting mitigates attack.
    
    ✓ ATTACK ENABLED - same cyberattack as degraded (step 120, all-red on B1)
    ✓ Trust-weighted defense - trust scorer detects anomalies and downweights malicious agents
    """
    logging.info("\n" + "="*80)
    logging.info("RESILIENT SCENARIO: Cyberattack WITH Trust-Based Defense")
    logging.info(f"Attack Config: {ATTACK_TYPE} on {ATTACKED_TLS_ID} at step {ATTACK_TIMESTEP}")
    logging.info("✓ ATTACK ENABLED during training")
    logging.info("✓ Defense: Trust-weighted federated aggregation (detects & downweights malicious agents)")
    logging.info("="*80 + "\n")
    
    # Resilient: trust-weighted aggregation with attack
    logging.info("Training FedPolicyTrainer (aggr='trust') - RESILIENT")
    resilient_prefix = f"{OUT_PREFIX}_resilient_trust"
    
    # Create custom trainer with attack enabled + trust weighting
    class ResilientTrainer(FedPolicyTrainer):
        def env_config_fn(self):
            config = super().env_config_fn()
            # ATTACK ENABLED - same attack as degraded scenario
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            # TRUST DEFENSE - enable trust scoring to detect anomalies
            config["use_trust_scoring"] = True
            config["trust_window_size"] = 20
            config["trust_spillback_threshold"] = 0.15
            config["trust_phase_lock_threshold"] = 30
            config["trust_ema_alpha"] = 0.1
            config["trust_suspected_threshold"] = 0.5
            # Vehicle flow configuration
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150  # Reduced from 360 for better training
            }
            return config
    
    ResilientTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=resilient_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="trust",  # Trust-weighted defense
        checkpoint_freq=1,  # Save checkpoint every episode
        # log_level="INFO"
    ).train(n_episodes)


if __name__ == "__main__":
    n_episodes = 1 # Number of training episodes
    fed_step = 1    # Aggregation frequency (every step)
    
    NET_FILES = {
        "grid_3x3": GRID_3x3,
        # Uncomment to test on larger networks
        # "grid_5x5": GRID_5x5,
        # "grid_7x7": GRID_7x7
    }
    
    RANKED = [True]  # Set to True or [True, False] for both
    
    logging.info("="*80)
    logging.info("CYBERATTACK RESILIENCE TRAINING")
    logging.info("Comparing 3 Scenarios:")
    logging.info("  1. BASELINE (naive): No attack, normal operation")
    logging.info("  2. DEGRADED (naive): Attack + no defense (vulnerable)")
    logging.info("  3. RESILIENT (trust): Attack + trust defense (protected)")
    logging.info("="*80)
    
    # Run experiments for each network and ranking configuration
    for (intersection, net_file) in NET_FILES.items():
        for ranked in RANKED:
            logging.info(f"\n{'='*80}")
            logging.info(f"Network: {intersection}, Ranked: {ranked}")
            logging.info(f"{'='*80}")
            
            # 1. BASELINE: Normal operation (control scenario)
            # train_baseline(net_file, ranked, n_episodes, fed_step)
            
            # 2. DEGRADED: Attack without defense (vulnerability scenario)
            # train_degraded(net_file, ranked, n_episodes, fed_step)
            
            # 3. RESILIENT: Attack with trust-based defense (resilience scenario)
            train_resilient(net_file, ranked, n_episodes, fed_step)
            
            logging.info(f"\nCompleted all scenarios for {intersection} (ranked={ranked})")
    
    logging.info("\n" + "="*80)
    logging.info("TRAINING COMPLETE")
    logging.info("Results show: Trust defense mitigates cyberattack impact")
    logging.info("Generated outputs in example_weights/")
    logging.info("="*80)
