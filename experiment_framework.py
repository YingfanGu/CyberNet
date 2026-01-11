"""
Phase 4: Experiment Framework for Trust-Based Resilience

Orchestrates 3-condition comparison experiments:
1. BASELINE: No attack - Normal traffic operation
2. DEGRADED: Attack without mitigation - Network degradation
3. RESILIENT: Attack with trust-weighted mitigation - Network recovery

All conditions run with identical configurations and random seeds for fair comparison.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, List
from netfiles import GRID_3x3
from seal.sumo.env import SumoEnv
from seal.logging import logging
from enum import Enum


class ExperimentCondition(Enum):
    """Experiment conditions for comparison."""
    BASELINE = "baseline"      # No attack
    DEGRADED = "degraded"      # Attack, no mitigation
    RESILIENT = "resilient"    # Attack + trust weighting


class ExperimentConfig:
    """Configuration for experiment scenarios."""
    
    def __init__(
        self,
        horizon: int = 360,
        attack_timestep: int = 120,
        attacked_tls_id: str = "B1",
        attack_type: str = "all_red",
        vehicles_per_lane_per_hour: int = 360,
        seed: int = 42
    ):
        self.horizon = horizon
        self.attack_timestep = attack_timestep
        self.attacked_tls_id = attacked_tls_id
        self.attack_type = attack_type
        self.vehicles_per_lane_per_hour = vehicles_per_lane_per_hour
        self.seed = seed


class ExperimentRunner:
    """
    Runs 3-condition traffic control experiments.
    
    Compares network behavior under:
    1. Normal operation (baseline)
    2. Cyberattack without defense (degraded)
    3. Cyberattack with trust-weighted defense (resilient)
    """
    
    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.results: Dict[ExperimentCondition, pd.DataFrame] = {}
        self.metrics_summary: Dict[ExperimentCondition, Dict] = {}
    
    def get_env_config(self, condition: ExperimentCondition) -> Dict:
        """Generate environment config for a specific condition."""
        base_config = {
            "net-file": GRID_3x3,
            "horizon": self.config.horizon,
            "ranked": False,
            "rand_routes_on_reset": True,
            "rand_route_args": {
                "vehicles_per_lane_per_hour": self.config.vehicles_per_lane_per_hour,
                "seed": self.config.seed,
            },
        }
        
        # Condition-specific settings
        if condition == ExperimentCondition.BASELINE:
            # No attack
            base_config["attack_timestep"] = None
            base_config["attacked_tls_id"] = None
        
        elif condition == ExperimentCondition.DEGRADED:
            # Attack without mitigation
            base_config["attack_timestep"] = self.config.attack_timestep
            base_config["attacked_tls_id"] = self.config.attacked_tls_id
            base_config["attack_type"] = self.config.attack_type
            base_config["use_trust_scoring"] = False  # No trust detection
        
        elif condition == ExperimentCondition.RESILIENT:
            # Attack with trust-weighted mitigation
            base_config["attack_timestep"] = self.config.attack_timestep
            base_config["attacked_tls_id"] = self.config.attacked_tls_id
            base_config["attack_type"] = self.config.attack_type
            base_config["use_trust_scoring"] = True  # Enable trust detection
            base_config["trust_window_size"] = 20
            base_config["trust_spillback_threshold"] = 0.15
            base_config["trust_phase_lock_threshold"] = 30
            base_config["trust_ema_alpha"] = 0.1
            base_config["trust_suspected_threshold"] = 0.5
        
        return base_config
    
    def run_condition(self, condition: ExperimentCondition) -> pd.DataFrame:
        """Run a single experiment condition."""
        
        logging.info("=" * 80)
        logging.info(f"EXPERIMENT CONDITION: {condition.value.upper()}")
        logging.info("=" * 80)
        
        env_config = self.get_env_config(condition)
        env = SumoEnv(config=env_config)
        
        # Results tracking
        results = {
            "step": [],
            "condition": [],
            "attacked_tls_occupancy": [],
            "attacked_tls_halted": [],
            "attacked_tls_trust_score": [],
            "attacked_tls_suspected": [],
            "network_avg_occupancy": [],
            "network_max_occupancy": [],
            "network_avg_halted": [],
            "under_attack": [],
            "num_vehicles": [],
        }
        
        # Run episode
        obs = env.reset()
        done = False
        step = 0
        
        while not done:
            # Random actions
            action_dict = {
                tls.id: env.action_space.sample()
                for tls in env.kernel.tls_hub
            }
            
            obs, reward, done, info = env.step(action_dict)
            
            # Log progress
            if step % 60 == 0 or step == self.config.attack_timestep:
                occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
                avg_occ = np.mean(occupancies) if occupancies else 0
                logging.info(f"Step {step}: avg_occupancy={avg_occ:.3f}")
                
                if step == self.config.attack_timestep and condition != ExperimentCondition.BASELINE:
                    logging.info(f"  [ATTACK TRIGGERED on {self.config.attacked_tls_id}]")
            
            # Collect metrics
            occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
            halted = [obs[tls.id][1] for tls in env.kernel.tls_hub]
            
            results["step"].append(step)
            results["condition"].append(condition.value)
            results["attacked_tls_occupancy"].append(obs[self.config.attacked_tls_id][0])
            results["attacked_tls_halted"].append(obs[self.config.attacked_tls_id][1])
            
            # Trust score (if available)
            if "trust_score" in info[self.config.attacked_tls_id]:
                results["attacked_tls_trust_score"].append(
                    info[self.config.attacked_tls_id]["trust_score"]
                )
                results["attacked_tls_suspected"].append(
                    info[self.config.attacked_tls_id]["is_suspected"]
                )
            else:
                results["attacked_tls_trust_score"].append(None)
                results["attacked_tls_suspected"].append(None)
            
            results["network_avg_occupancy"].append(np.mean(occupancies))
            results["network_max_occupancy"].append(np.max(occupancies))
            results["network_avg_halted"].append(np.mean(halted))
            results["under_attack"].append(
                self.config.attack_timestep is not None and 
                step >= self.config.attack_timestep
            )
            results["num_vehicles"].append(env.kernel.get_num_of_vehicles())
            
            step += 1
        
        env.close()
        
        df = pd.DataFrame(results)
        self.results[condition] = df
        self._compute_metrics(condition, df)
        
        logging.info(f"Completed {condition.value} condition\n")
        
        return df
    
    def _compute_metrics(self, condition: ExperimentCondition, df: pd.DataFrame) -> None:
        """Compute summary metrics for a condition."""
        
        # Pre/post attack phases (only relevant for non-baseline)
        if condition == ExperimentCondition.BASELINE:
            pre = df[df["step"] < self.config.attack_timestep]
            post = df[df["step"] >= self.config.attack_timestep]
        else:
            pre = df[df["step"] < self.config.attack_timestep]
            post = df[df["step"] >= self.config.attack_timestep]
        
        metrics = {
            "condition": condition.value,
            "total_steps": len(df),
            
            # Pre-attack metrics
            "pre_network_avg_occupancy": pre['network_avg_occupancy'].mean(),
            "pre_attacked_occupancy": pre['attacked_tls_occupancy'].mean(),
            "pre_network_max_occupancy": pre['network_max_occupancy'].mean(),
            
            # Post-attack metrics (or full episode for baseline)
            "post_network_avg_occupancy": post['network_avg_occupancy'].mean(),
            "post_attacked_occupancy": post['attacked_tls_occupancy'].mean(),
            "post_network_max_occupancy": post['network_max_occupancy'].mean(),
            "post_network_avg_halted": post['network_avg_halted'].mean(),
            
            # Impact metrics
            "occupancy_increase": (
                post['network_avg_occupancy'].mean() - 
                pre['network_avg_occupancy'].mean()
            ),
            "attacked_occupancy_increase": (
                post['attacked_tls_occupancy'].mean() - 
                pre['attacked_tls_occupancy'].mean()
            ),
        }
        
        # Trust metrics (if available)
        if df['attacked_tls_trust_score'].notna().any():
            metrics["avg_trust_score_pre"] = pre['attacked_tls_trust_score'].mean()
            metrics["avg_trust_score_post"] = post['attacked_tls_trust_score'].mean()
            metrics["trust_decay"] = (
                pre['attacked_tls_trust_score'].mean() - 
                post['attacked_tls_trust_score'].mean()
            )
            metrics["suspected_fraction_post"] = post['attacked_tls_suspected'].mean()
        
        self.metrics_summary[condition] = metrics
    
    def run_all_conditions(self) -> None:
        """Run all 3 experiment conditions."""
        for condition in [ExperimentCondition.BASELINE, 
                         ExperimentCondition.DEGRADED, 
                         ExperimentCondition.RESILIENT]:
            self.run_condition(condition)
    
    def save_results(self, output_prefix: str = "experiment") -> None:
        """Save results to CSV files."""
        for condition, df in self.results.items():
            filename = f"{output_prefix}_{condition.value}_results.csv"
            df.to_csv(filename, index=False)
            logging.info(f"Saved: {filename}")
    
    def print_summary(self) -> None:
        """Print summary statistics."""
        print("\n" + "=" * 80)
        print("EXPERIMENT SUMMARY STATISTICS")
        print("=" * 80 + "\n")
        
        summary_df = pd.DataFrame(self.metrics_summary.values())
        print(summary_df.to_string(index=False))
        
        print("\n" + "=" * 80)
        print("DETAILED COMPARISON")
        print("=" * 80 + "\n")
        
        # Pre-attack baseline
        baseline_pre = self.metrics_summary[ExperimentCondition.BASELINE]['pre_network_avg_occupancy']
        
        for condition in [ExperimentCondition.DEGRADED, ExperimentCondition.RESILIENT]:
            metrics = self.metrics_summary[condition]
            occ_increase = metrics['occupancy_increase']
            
            print(f"\n{condition.value.upper()}:")
            print(f"  Pre-attack occupancy:  {metrics['pre_network_avg_occupancy']:.4f}")
            print(f"  Post-attack occupancy: {metrics['post_network_avg_occupancy']:.4f}")
            print(f"  Occupancy increase: +{occ_increase:.4f} ({occ_increase*100:.1f}%)")
            
            if 'trust_decay' in metrics:
                print(f"  Trust decay: {metrics['trust_decay']:.4f}")
                print(f"  Suspected agents: {metrics['suspected_fraction_post']:.1%}")
        
        # Comparison: Resilient vs Degraded
        degraded_occ = self.metrics_summary[ExperimentCondition.DEGRADED]['post_network_avg_occupancy']
        resilient_occ = self.metrics_summary[ExperimentCondition.RESILIENT]['post_network_avg_occupancy']
        improvement = degraded_occ - resilient_occ
        
        print(f"\nRESILIENCE IMPROVEMENT:")
        print(f"  Degraded (post-attack):  {degraded_occ:.4f}")
        print(f"  Resilient (post-attack): {resilient_occ:.4f}")
        print(f"  Improvement: {improvement:.4f} ({improvement*100:.1f}% better)")
        
        print("\n" + "=" * 80)


def main():
    """Run the full 3-condition experiment."""
    
    # Experiment configuration
    config = ExperimentConfig(
        horizon=360,
        attack_timestep=120,
        attacked_tls_id="B1",
        attack_type="all_red",
        vehicles_per_lane_per_hour=360,
        seed=42
    )
    
    # Create and run experiment
    runner = ExperimentRunner(config)
    
    logging.info("\n" + "=" * 80)
    logging.info("PHASE 4: EXPERIMENT FRAMEWORK - 3-CONDITION COMPARISON")
    logging.info("=" * 80)
    logging.info(f"Horizon: {config.horizon} steps")
    logging.info(f"Attack at step: {config.attack_timestep}")
    logging.info(f"Attacked TLS: {config.attacked_tls_id}")
    logging.info(f"Random seed: {config.seed}\n")
    
    # Run all conditions
    runner.run_all_conditions()
    
    # Save and display results
    runner.save_results("cyberattack_experiment")
    runner.print_summary()


if __name__ == "__main__":
    main()
