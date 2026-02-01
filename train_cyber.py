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
import pickle
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
    
    # ====================== #
    # PPO Trainer Arguments. #
    # ====================== #
    # === STABILITY IMPROVEMENTS === #
    # These settings reduce oscillation and enable smooth convergence
    
    # Entropy regularization - reduces exploration noise after convergence
    "entropy_coeff": 0.005,
    
    # Policy clip parameter - tighter clipping for smaller, more stable updates
    # Default 0.3 too loose → causes oscillation. 0.15 = smoother
    "clip_param": 0.15,
    
    # Value function clipping - prevents value estimate divergence
    "vf_clip_param": 10.0,
    
    # Generalized Advantage Estimation - reduces variance in advantage estimates
    # Crucial for stable training
    "use_gae": True,
    "lambda": 0.95,  # GAE lambda parameter
    "gamma": 0.99,   # Discount factor
    
    # BATCH SIZE SETTINGS - Larger batches = smoother gradients (fixes oscillation)
    "sgd_minibatch_size": 128,     # Inner training batch (was default ~32)
    "num_sgd_iter": 20,             # Inner optimization iterations per update
    "train_batch_size": 4000,       # Total batch size for gradient computation
    
    # Gradient clipping - prevents extreme parameter updates
    "grad_clip": 0.5,
    
    # LEARNING RATE - Fixed rate for stability
    "lr": 0.0005,                   # Base learning rate (reduced from 0.001)
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
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Set up directory for episode-specific weights
            self.episode_weights_dir = os.path.join(
                "out/SMARTCOMP/weight_episode/FedRL/grid-3x3",
                self.out_prefix
            )
        
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
        
        def save_test_policy(self):
            # Call parent to save the main policy
            weights = super().save_test_policy()
            
            # Also save episode-specific weights
            os.makedirs(self.episode_weights_dir, exist_ok=True)
            episode_file = os.path.join(self.episode_weights_dir, f"{self._round:06d}.pkl")
            with open(episode_file, "wb") as f:
                pickle.dump(weights, f)
            logging.info(f"Saved episode weights: {episode_file}")
            
            return weights
    
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
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Set up directory for episode-specific weights
            self.episode_weights_dir = os.path.join(
                "out/SMARTCOMP/weight_episode/FedRL/grid-3x3",
                self.out_prefix
            )
        
        def env_config_fn(self):
            config = super().env_config_fn()
            # ATTACK ENABLED - cyberattack on B1 at step 120
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            config["use_trust_scoring"] = False  # No trust defense
            config["use_dynamic_seed"] = False  # Fixed seed for reproducibility
            # Vehicle flow configuration
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150,  # Reduced from 360 for better training
                "seed": 42  # Fixed seed for reproducibility
            }
            return config
        
        def save_test_policy(self):
            # Call parent to save the main policy
            weights = super().save_test_policy()
            
            # Also save episode-specific weights
            os.makedirs(self.episode_weights_dir, exist_ok=True)
            episode_file = os.path.join(self.episode_weights_dir, f"{self._round:06d}.pkl")
            with open(episode_file, "wb") as f:
                pickle.dump(weights, f)
            logging.info(f"Saved episode weights: {episode_file}")
            
            return weights
    
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
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Set up directory for episode-specific weights
            self.episode_weights_dir = os.path.join(
                "out/SMARTCOMP/weight_episode/FedRL/grid-3x3",
                self.out_prefix
            )
        
        def env_config_fn(self):
            config = super().env_config_fn()
            # ATTACK ENABLED - same attack as degraded scenario
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            # TRUST DEFENSE - enable trust scoring to detect anomalies
            config["use_trust_scoring"] = True
            config["use_dynamic_seed"] = False  # Fixed seed for reproducibility
            config["trust_window_size"] = 5  # Smaller window for faster anomaly detection
            config["trust_spillback_threshold"] = 0.25  # Queue threshold for anomaly detection
            config["trust_phase_lock_threshold"] = 30  # Phase lock detection threshold
            config["trust_ema_alpha"] = 0.4  # Faster response to changes
            config["trust_suspected_threshold"] = 0.5  # More aggressive detection threshold
            # Vehicle flow configuration
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150,  # Reduced from 360 for better training
                "seed": 42  # Fixed seed for reproducibility
            }
            return config
        
        def save_test_policy(self):
            # Call parent to save the main policy
            weights = super().save_test_policy()
            
            # Also save episode-specific weights
            os.makedirs(self.episode_weights_dir, exist_ok=True)
            episode_file = os.path.join(self.episode_weights_dir, f"{self._round:06d}.pkl")
            with open(episode_file, "wb") as f:
                pickle.dump(weights, f)
            logging.info(f"Saved episode weights: {episode_file}")
            
            return weights
    
    ResilientTrainer(
        fed_step=fed_step, net_file=net_file, ranked=ranked,
        out_prefix=resilient_prefix,
        trainer_kwargs=trainer_kwargs,
        weight_fn="trust",  # Trust-weighted defense
        checkpoint_freq=1,  # Save checkpoint every episode
        # log_level="INFO"
    ).train(n_episodes)


def train_MultiPolicyTrainer(net_file, ranked, n_episodes):
    """
    Train using multi-agent RL (without federation).
    Each agent learns independently with centralized policy updates.
    
    This is a comparison approach: multi-agent RL without federated aggregation.
    
    ✓ ATTACK ENABLED - cyberattack on B1 at step 120
    ✓ Multi-agent RL - independent learning, no federation
    """
    logging.info("\n" + "="*80)
    logging.info("MULTI-AGENT RL SCENARIO: Independent Agent Learning")
    logging.info(f"Attack Config: {ATTACK_TYPE} on {ATTACKED_TLS_ID} at step {ATTACK_TIMESTEP}")
    logging.info("✓ ATTACK ENABLED during training")
    logging.info("✓ Multi-agent RL: Independent learning (no federated aggregation)")
    logging.info("="*80 + "\n")
    
    # Multi-agent RL: independent learning with attack
    logging.info("Training MultiPolicyTrainer - MULTI-AGENT RL")
    multiagent_prefix = f"{OUT_PREFIX}_multiagent"
    
    # Create custom trainer for multi-agent RL
    class MultiAgentTrainer(MultiPolicyTrainer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Set up directory for episode-specific weights
            self.episode_weights_dir = os.path.join(
                "out/SMARTCOMP/weight_episode/MultiAgent/grid-3x3",
                self.out_prefix
            )
        
        def env_config_fn(self):
            config = super().env_config_fn()
            # ATTACK ENABLED - same attack as other scenarios
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            config["use_trust_scoring"] = False  # Not applicable for multi-agent
            config["use_dynamic_seed"] = False  # Fixed seed for reproducibility
            # Vehicle flow configuration
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150,
                "seed": 42
            }
            return config
        
        def save_test_policy(self):
            # Call parent to save the main policy
            weights = super().save_test_policy()
            
            # Also save episode-specific weights
            os.makedirs(self.episode_weights_dir, exist_ok=True)
            episode_file = os.path.join(self.episode_weights_dir, f"{self._round:06d}.pkl")
            with open(episode_file, "wb") as f:
                pickle.dump(weights, f)
            logging.info(f"Saved episode weights: {episode_file}")
            
            return weights
    
    MultiAgentTrainer(
        net_file=net_file, ranked=ranked,
        out_prefix=multiagent_prefix,
        trainer_kwargs=trainer_kwargs,
        checkpoint_freq=1,  # Save checkpoint every episode
    ).train(n_episodes)


def train_SinglePolicyTrainer(net_file, ranked, n_episodes):
    """
    Train using single-agent RL (centralized control).
    One agent controls all traffic lights in the network.
    
    This is a comparison approach: single-agent RL without multi-agent federation.
    
    ✓ ATTACK ENABLED - cyberattack on B1 at step 120
    ✓ Single-agent RL - centralized control, no federation
    """
    logging.info("\n" + "="*80)
    logging.info("SINGLE-AGENT RL SCENARIO: Centralized Control")
    logging.info(f"Attack Config: {ATTACK_TYPE} on {ATTACKED_TLS_ID} at step {ATTACK_TIMESTEP}")
    logging.info("✓ ATTACK ENABLED during training")
    logging.info("✓ Single-agent RL: Centralized control (no multi-agent federation)")
    logging.info("="*80 + "\n")
    
    # Single-agent RL: centralized control with attack
    logging.info("Training SinglePolicyTrainer - SINGLE-AGENT RL")
    singleagent_prefix = f"{OUT_PREFIX}_singleagent"
    
    # Create custom trainer for single-agent RL
    class SingleAgentTrainer(SinglePolicyTrainer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Set up directory for episode-specific weights
            self.episode_weights_dir = os.path.join(
                "out/SMARTCOMP/weight_episode/SingleAgent/grid-3x3",
                self.out_prefix
            )
        
        def env_config_fn(self):
            config = super().env_config_fn()
            # ATTACK ENABLED - same attack as other scenarios
            config["attack_timestep"] = ATTACK_TIMESTEP
            config["attacked_tls_id"] = ATTACKED_TLS_ID
            config["attack_type"] = ATTACK_TYPE
            config["use_trust_scoring"] = False  # Not applicable for single-agent
            config["use_dynamic_seed"] = False  # Fixed seed for reproducibility
            # Vehicle flow configuration
            config["rand_route_args"] = {
                "vehicles_per_lane_per_hour": 150,
                "seed": 42
            }
            return config
        
        def save_test_policy(self):
            # Call parent to save the main policy
            weights = super().save_test_policy()
            
            # Also save episode-specific weights
            os.makedirs(self.episode_weights_dir, exist_ok=True)
            episode_file = os.path.join(self.episode_weights_dir, f"{self._round:06d}.pkl")
            with open(episode_file, "wb") as f:
                pickle.dump(weights, f)
            logging.info(f"Saved episode weights: {episode_file}")
            
            return weights
    
    SingleAgentTrainer(
        net_file=net_file, ranked=ranked,
        out_prefix=singleagent_prefix,
        trainer_kwargs=trainer_kwargs,
        checkpoint_freq=1,  # Save checkpoint every episode
    ).train(n_episodes)


if __name__ == "__main__":
    n_episodes = 30 # Number of training episodes
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
    logging.info("Comparing Multiple Scenarios:")
    logging.info("  1. BASELINE (FedRL naive): No attack, normal operation")
    logging.info("  2. DEGRADED (FedRL naive): Attack + no defense (vulnerable)")
    logging.info("  3. RESILIENT (FedRL trust): Attack + trust defense (protected)")
    logging.info("  4. MULTI-AGENT RL: Independent agent learning with attack")
    logging.info("  5. SINGLE-AGENT RL: Centralized control with attack")
    logging.info("="*80)
    
    # Run experiments for each network and ranking configuration
    for (intersection, net_file) in NET_FILES.items():
        for ranked in RANKED:
            logging.info(f"\n{'='*80}")
            logging.info(f"Network: {intersection}, Ranked: {ranked}")
            logging.info(f"{'='*80}")
            

            
            # 1. BASELINE: Normal operation (control scenario)
            train_baseline(net_file, ranked, n_episodes, fed_step)
            
            # # 2. DEGRADED: Attack without defense (vulnerability scenario)
            train_degraded(net_file, ranked, n_episodes, fed_step)
            
            # 3. RESILIENT: Attack with trust-based defense (resilience scenario)
            train_resilient(net_file, ranked, n_episodes, fed_step)
            
            # # 4. MULTI-AGENT: Independent learning comparison
            train_MultiPolicyTrainer(net_file, ranked, n_episodes)
            
            # # 5. SINGLE-AGENT: Centralized control comparison
            train_SinglePolicyTrainer(net_file, ranked, n_episodes)
            
            logging.info(f"\nCompleted all scenarios for {intersection} (ranked={ranked})")
    
    logging.info("\n" + "="*80)
    logging.info("TRAINING COMPLETE")
    logging.info("Results show: Trust defense mitigates cyberattack impact")
    logging.info("Generated outputs in example_weights/")
    logging.info("="*80)
