"""
Test script to verify Trust Scorer integration with SumoEnv and cyberattack.

This script runs the 3x3 grid simulation with:
1. Cyberattack injection at step 120 on B1
2. Trust scoring enabled to detect the attack
3. Logs trust score decay as attack progresses

Verifies that trust scorer successfully detects attacks via:
- Spillback detection (queue buildup at B1)
- Phase lock detection (B1 stuck in all-red)
"""

import pandas as pd
from netfiles import GRID_3x3
from seal.sumo.env import SumoEnv
from seal.logging import logging


def run_test_with_trust():
    """Run cyberattack test with trust scoring enabled."""
    
    # Environment configuration with trust scoring
    env_config = {
        "net-file": GRID_3x3,
        "horizon": 360,
        "ranked": False,
        "rand_routes_on_reset": True,
        "rand_route_args": {
            "vehicles_per_lane_per_hour": 360,
        },
        # Cyberattack configuration
        "attack_timestep": 120,
        "attacked_tls_id": "B1",
        "attack_type": "all_red",
        # Trust scoring configuration
        "use_trust_scoring": True,
        "trust_window_size": 20,
        "trust_spillback_threshold": 0.15,
        "trust_phase_lock_threshold": 30,
        "trust_ema_alpha": 0.1,
        "trust_suspected_threshold": 0.5,
    }
    
    # Create environment with trust scoring
    env = SumoEnv(config=env_config)
    
    # Tracking lists
    results = {
        "step": [],
        "B1_occupancy": [],
        "B1_trust_score": [],
        "B1_suspected": [],
        "B1_spillback": [],
        "B1_phase_lock": [],
        "under_attack": [],
        "network_avg_occupancy": [],
    }
    
    logging.info("=" * 80)
    logging.info("CYBERATTACK TEST WITH TRUST SCORING")
    logging.info("=" * 80)
    logging.info(f"Horizon: 360 steps")
    logging.info(f"Attack at step: 120")
    logging.info(f"Attacked TLS: B1")
    logging.info(f"Trust scoring: ENABLED\n")
    
    # Run episode
    obs = env.reset()
    done = False
    step = 0
    
    while not done:
        # Take random actions
        action_dict = {
            tls.id: env.action_space.sample()
            for tls in env.kernel.tls_hub
        }
        
        obs, reward, done, info = env.step(action_dict)
        
        # Get attacked TLS for reference
        attacked_tls = env.kernel.tls_hub["B1"]
        
        # Log every 60 steps + attack trigger
        if step % 60 == 0 or step == 120:
            occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
            avg_occupancy = sum(occupancies) / len(occupancies) if occupancies else 0
            
            logging.info(f"Step {step}:")
            logging.info(f"  B1 occupancy: {obs['B1'][0]:.3f}")
            logging.info(f"  B1 trust score: {info['B1']['trust_score']:.3f}")
            logging.info(f"  B1 suspected: {info['B1']['is_suspected']}")
            logging.info(f"  Network avg occupancy: {avg_occupancy:.3f}")
            
            if step == 120:
                logging.info(f"  [ATTACK TRIGGERED]")
        
        # Track results
        occupancies = [obs[tls.id][0] for tls in env.kernel.tls_hub]
        results["step"].append(step)
        results["B1_occupancy"].append(obs["B1"][0])
        results["B1_trust_score"].append(info["B1"]["trust_score"])
        results["B1_suspected"].append(info["B1"]["is_suspected"])
        
        # Get anomaly signals if available
        if env.trust_scorer is not None:
            anomalies = env.trust_scorer.get_anomaly_signals("B1")
            results["B1_spillback"].append(anomalies["spillback"])
            results["B1_phase_lock"].append(anomalies["phase_lock"])
        else:
            results["B1_spillback"].append(False)
            results["B1_phase_lock"].append(False)
        
        results["under_attack"].append(attacked_tls.is_under_attack)
        results["network_avg_occupancy"].append(
            sum(occupancies) / len(occupancies) if occupancies else 0
        )
        
        step += 1
    
    # Save results
    df = pd.DataFrame(results)
    df.to_csv("cyberattack_with_trust_results.csv", index=False)
    logging.info("\nResults saved to cyberattack_with_trust_results.csv")
    
    # Print summary
    print("\n" + "=" * 80)
    print("CYBERATTACK WITH TRUST SCORING - SUMMARY")
    print("=" * 80 + "\n")
    
    pre_attack = df[df["step"] < 120]
    post_attack = df[df["step"] >= 120]
    
    print("Pre-Attack (steps 0-119):")
    print(f"  B1 avg trust score: {pre_attack['B1_trust_score'].mean():.4f}")
    print(f"  B1 avg occupancy: {pre_attack['B1_occupancy'].mean():.4f}")
    print(f"  Network avg occupancy: {pre_attack['network_avg_occupancy'].mean():.4f}")
    
    print("\nPost-Attack (steps 120-359):")
    print(f"  B1 avg trust score: {post_attack['B1_trust_score'].mean():.4f}")
    print(f"  B1 avg occupancy: {post_attack['B1_occupancy'].mean():.4f}")
    print(f"  B1 avg suspected: {post_attack['B1_suspected'].mean():.2%}")
    print(f"  B1 spillback detected: {post_attack['B1_spillback'].sum()} / {len(post_attack)} steps ({post_attack['B1_spillback'].mean():.1%})")
    print(f"  B1 phase lock detected: {post_attack['B1_phase_lock'].sum()} / {len(post_attack)} steps ({post_attack['B1_phase_lock'].mean():.1%})")
    print(f"  Network avg occupancy: {post_attack['network_avg_occupancy'].mean():.4f}")
    
    # Attack impact
    trust_decay = pre_attack['B1_trust_score'].mean() - post_attack['B1_trust_score'].mean()
    occupancy_increase = post_attack['network_avg_occupancy'].mean() - pre_attack['network_avg_occupancy'].mean()
    
    print("\nAttack Impact:")
    print(f"  Trust decay: {trust_decay:.4f} ({trust_decay*100:.1f}% decrease)")
    print(f"  Occupancy increase: {occupancy_increase:.4f} ({occupancy_increase*100:.1f}% increase)")
    
    # Verify trust detection
    print("\n" + "=" * 80)
    print("ATTACK DETECTION VERIFICATION:")
    print("=" * 80)
    
    detection_checks = {
        "Pre-attack trust ≈ 1.0": pre_attack['B1_trust_score'].mean() > 0.95,
        "Post-attack trust decayed": post_attack['B1_trust_score'].mean() < pre_attack['B1_trust_score'].mean(),
        "Spillback detected": post_attack['B1_spillback'].sum() > 0,
        "Phase lock detected": post_attack['B1_phase_lock'].sum() > 0,
        "Network occupancy increased": occupancy_increase > 0,
    }
    
    for check, passed in detection_checks.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {check}")
    
    all_passed = all(detection_checks.values())
    print(f"\n{'='*80}")
    print(f"Overall: {'✓ INTEGRATION SUCCESSFUL' if all_passed else '✗ SOME CHECKS FAILED'}")
    print(f"{'='*80}")


if __name__ == "__main__":
    run_test_with_trust()
