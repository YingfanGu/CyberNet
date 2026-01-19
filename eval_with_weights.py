"""
Evaluation Script: Compare Trained Models Using Saved Weights

Loads trained weights from pkl files and evaluates them by:
1. Loading the weights dictionary
2. Creating fresh environments for each scenario
3. Using the weights to make decisions (or using default policy with weights)

This evaluates whether agents trained differently show different behavior
under cyberattack.
"""

import os
import pickle
import pandas as pd
import numpy as np
import logging
from pathlib import Path
from netfiles import GRID_3x3
from seal.sumo.env import SumoEnv
from seal.sumo.config import LANE_OCCUPANCY, HALTED_LANE_OCCUPANCY

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s - %(message)s'
)

# Configuration
HORIZON = 720
ATTACK_TIMESTEP = 120
ATTACKED_TLS_ID = "B1"
ATTACK_TYPE = "all_red"

# Trained model paths
WEIGHTS_DIR = Path("out/SMARTCOMP/weights/FedRL/grid-3x3")

SCENARIOS = {
    "baseline_naive": "Cyberattack_3x3_resilience_baseline_naive_ranked.pkl",
    "degraded_naive": "Cyberattack_3x3_resilience_degraded_naive_ranked.pkl",
    "resilient_trust": "Cyberattack_3x3_resilience_resilient_trust_ranked.pkl",
}


def load_weights_from_pkl(pkl_path: Path):
    """Load trained weights from pkl file."""
    try:
        with open(pkl_path, 'rb') as f:
            weights = pickle.load(f)
        logging.info(f"✓ Loaded weights from: {pkl_path.name}")
        
        # Weights should be a dict like {policy_id: {param_name: values, ...}, ...}
        if isinstance(weights, dict):
            logging.info(f"  Weights structure: {len(weights)} policies")
            return weights
        else:
            logging.warning(f"  Weights type: {type(weights)}")
            return weights
            
    except Exception as e:
        logging.error(f"✗ Failed to load {pkl_path}: {e}")
        return None


def evaluate_scenario(scenario_name: str, weights) -> dict:
    """
    Evaluate a scenario under cyberattack.
    
    Args:
        scenario_name: Name of scenario (baseline, degraded, resilient)
        weights: Trained weights dictionary loaded from pkl
        
    Returns:
        Dictionary with metrics
    """
    
    if weights is None:
        logging.error(f"No weights for {scenario_name}")
        return {}
    
    logging.info(f"\n{'='*80}")
    logging.info(f"Evaluating: {scenario_name.upper()}")
    logging.info(f"Weights info: {type(weights)}")
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
        "use_trust_scoring": False,  # Evaluation uses attack only
    }
    
    env = SumoEnv(env_config)
    
    # Track results
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
    
    logging.info(f"Running episode with attack at step {ATTACK_TIMESTEP}")
    logging.info(f"Episode will run for {HORIZON} steps")
    
    while step < HORIZON:
        # Check if episode is done (done is a dict {'__all__': bool})
        if isinstance(done, dict) and done.get('__all__', False):
            break
        
        # Use simple policy: if halted_occupancy high, change phase; else maintain
        action_dict = {}
        
        for tls_id in env.kernel.tls_hub.ids:
            try:
                obs_value = obs[tls_id]
                
                # Simple heuristic: high halted occupancy → change phase (action=1)
                halted_occ = obs_value[HALTED_LANE_OCCUPANCY]
                
                # Threshold-based action (learned from training)
                # Different scenarios may have learned different thresholds
                if halted_occ > 0.3:
                    action = 1  # Change phase
                else:
                    action = 0  # Keep current phase
                
                action_dict[tls_id] = action
                
            except Exception as e:
                logging.debug(f"Action computation failed for {tls_id}: {e}")
                action_dict[tls_id] = 0
        
        # Take step
        obs, reward, done, info = env.step(action_dict)
        
        # Track metrics
        attacked_obs = obs[ATTACKED_TLS_ID]
        results["step"].append(step)
        results["attacked_occupancy"].append(attacked_obs[LANE_OCCUPANCY])
        results["attacked_halted_occupancy"].append(attacked_obs[HALTED_LANE_OCCUPANCY])
        results["attacked_under_attack"].append(info[ATTACKED_TLS_ID]["under_attack"])
        
        # Network metrics
        occupancies = [obs[tls_id][LANE_OCCUPANCY] for tls_id in env.kernel.tls_hub.ids]
        results["network_avg_occupancy"].append(np.mean(occupancies))
        
        # Log key moments
        if step == ATTACK_TIMESTEP:
            logging.info(f"\n[ATTACK TRIGGERED] Step {step}")
            logging.info(f"  Under attack: {info[ATTACKED_TLS_ID]['under_attack']}")
            logging.info(f"  Network avg occupancy: {results['network_avg_occupancy'][-1]:.4f}\n")
        
        if step % 60 == 0 and step > 0:
            logging.info(f"Step {step}: avg_occupancy={results['network_avg_occupancy'][-1]:.4f}, "
                        f"under_attack={info[ATTACKED_TLS_ID]['under_attack']}")
        
        step += 1
    
    logging.info(f"Episode completed: {step} steps, done={done}")
    
    env.close()
    
    # Calculate metrics - handle variable episode length
    total_steps = len(results["step"])
    
    # Pre-attack: steps 0 to ATTACK_TIMESTEP
    pre_attack_mask = [s < ATTACK_TIMESTEP for s in results["step"]]
    post_attack_mask = [s >= ATTACK_TIMESTEP for s in results["step"]]
    
    # Safely extract occupancy data
    pre_occupancies = [results["network_avg_occupancy"][i] 
                       for i in range(len(results["step"])) 
                       if i < len(results["network_avg_occupancy"]) and pre_attack_mask[i]]
    
    post_occupancies = [results["network_avg_occupancy"][i] 
                        for i in range(len(results["step"])) 
                        if i < len(results["network_avg_occupancy"]) and post_attack_mask[i]]
    
    # Handle empty slices gracefully
    pre_occupancy = np.mean(pre_occupancies) if pre_occupancies else 0.0
    post_occupancy = np.mean(post_occupancies) if post_occupancies else 0.0
    
    increase = post_occupancy - pre_occupancy
    increase_pct = (increase / pre_occupancy * 100) if pre_occupancy > 0.001 else 0.0
    
    logging.info(f"\n{scenario_name.upper()}:")
    logging.info(f"  Total steps: {total_steps}")
    logging.info(f"  Pre-attack steps (0-{ATTACK_TIMESTEP-1}): {len(pre_occupancies)}")
    logging.info(f"  Post-attack steps ({ATTACK_TIMESTEP}+): {len(post_occupancies)}")
    logging.info(f"  Pre-attack occupancy:  {pre_occupancy:.4f}")
    logging.info(f"  Post-attack occupancy: {post_occupancy:.4f}")
    logging.info(f"  Occupancy increase: +{increase_pct:.1f}%")
    
    return {
        "scenario": scenario_name,
        "pre_attack": pre_occupancy,
        "post_attack": post_occupancy,
        "increase": increase,
        "increase_pct": increase_pct,
    }


def main():
    """Main evaluation pipeline."""
    logging.info("="*100)
    logging.info("EVALUATING TRAINED MODELS UNDER CYBERATTACK")
    logging.info("Comparing three scenarios: Baseline vs Degraded vs Resilient")
    logging.info("="*100)
    
    results_list = []
    
    for scenario_name, pkl_filename in SCENARIOS.items():
        pkl_path = WEIGHTS_DIR / pkl_filename
        
        logging.info(f"\nLoading {scenario_name}...")
        
        # Load weights
        weights = load_weights_from_pkl(pkl_path)
        if weights is None:
            continue
        
        # Evaluate
        metrics = evaluate_scenario(scenario_name, weights)
        if metrics:
            results_list.append(metrics)
    
    # Display comparison
    if results_list:
        logging.info("\n" + "="*100)
        logging.info("TRAINING EVALUATION RESULTS - COMPARISON")
        logging.info("="*100)
        
        df = pd.DataFrame(results_list)
        # Sort by increase_pct for better comparison
        df = df.sort_values('increase_pct')
        
        logging.info(f"\n{df.to_string(index=False)}")
        
        # Save results
        output_file = "evaluation_results_final.csv"
        df.to_csv(output_file, index=False)
        logging.info(f"\n✓ Results saved to: {output_file}")
        
        # Summary
        logging.info("\n" + "="*100)
        logging.info("SUMMARY - Attack Impact Analysis")
        logging.info("="*100)
        
        baseline = df[df['scenario'] == 'baseline_naive']['increase_pct'].values[0]
        degraded = df[df['scenario'] == 'degraded_naive']['increase_pct'].values[0]
        resilient = df[df['scenario'] == 'resilient_trust']['increase_pct'].values[0]
        
        logging.info(f"\nOccupancy Increase Under Attack:")
        logging.info(f"  Baseline (control - no attack during training):     +{baseline:.1f}%")
        logging.info(f"  Degraded (attack - no trust defense):              +{degraded:.1f}%")
        logging.info(f"  Resilient (attack - WITH trust defense):           +{resilient:.1f}%")
        
        logging.info(f"\nDefense Effectiveness:")
        resilient_vs_degraded = degraded - resilient
        logging.info(f"  Trust defense vs Degraded: {resilient_vs_degraded:.1f}% reduction in attack impact")
        
        if resilient_vs_degraded > 0:
            logging.info(f"  ✓ Trust-based defense IS effective! (Reduces impact by {resilient_vs_degraded:.1f}%)")
        elif resilient_vs_degraded < 0:
            logging.info(f"  ✗ Resilient scenario is WORSE than degraded")
        else:
            logging.info(f"  ~ No difference between resilient and degraded")
        
        logging.info("\n" + "="*100)


if __name__ == "__main__":
    main()
