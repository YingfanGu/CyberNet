"""
Test script for Trust Scorer Module.

Verifies that the trust scorer correctly:
1. Initializes with full trust (1.0) for all intersections
2. Detects spillback anomalies (occupancy spikes)
3. Detects phase lock (stuck traffic light)
4. Decays trust scores when anomalies detected
5. Recovers trust when normal behavior resumes
"""

import pandas as pd
import numpy as np
from seal.trust import TrustScorer
from seal.logging import logging


def test_trust_scorer():
    """Test trust scorer with synthetic data."""
    
    # Simulate 3x3 grid network (like SMARTCOMP)
    tls_ids = ["A0", "A1", "A2", "B0", "B1", "B2", "C0", "C1", "C2"]
    
    # Simple grid adjacency: each TLS connects to neighbors
    tls_graph = {
        "A0": ["A1", "B0"],      # A0 -> A1, B0
        "A1": ["A0", "A2", "B1"],
        "A2": ["A1", "B2"],
        "B0": ["A0", "B1", "C0"],
        "B1": ["A1", "B0", "B2", "C1"],  # Center - attacked
        "B2": ["A2", "B1", "C2"],
        "C0": ["B0", "C1"],
        "C1": ["B1", "C0", "C2"],
        "C2": ["B2", "C1"],
    }
    
    # Initialize trust scorer
    scorer = TrustScorer(
        tls_graph=tls_graph,
        tls_ids=tls_ids,
        window_size=20,
        spillback_threshold=0.15,
        phase_lock_threshold=30
    )
    
    logging.info("=" * 80)
    logging.info("TRUST SCORER TEST")
    logging.info("=" * 80)
    logging.info(f"Network: 3x3 grid with {len(tls_ids)} intersections")
    logging.info(f"Attacked intersection: B1 (center)\n")
    
    # Track results
    results = {
        "step": [],
        "B1_occupancy": [],
        "B1_phase": [],
        "B1_trust_score": [],
        "B1_suspected": [],
        "B1_spillback": [],
        "B1_phase_lock": [],
        "A1_trust_score": [],
        "B0_trust_score": [],
    }
    
    # Test scenario:
    # Steps 0-50: Normal operation (baseline)
    # Steps 50-100: B1 under attack (all-red, queues build)
    # Steps 100-150: Recovery (attack ends, traffic normalizes)
    
    normal_occupancy = 0.15
    attacked_occupancy = 0.45
    
    for step in range(150):
        # Create synthetic occupancy data
        occupancies = {}
        
        if step < 50:
            # Normal operation
            occupancies = {tls_id: normal_occupancy + np.random.normal(0, 0.05) 
                          for tls_id in tls_ids}
        elif step < 100:
            # B1 under attack (all-red)
            # B1 occupancy spikes, neighbors also increase (spillback)
            occupancies = {tls_id: normal_occupancy + np.random.normal(0, 0.05) 
                          for tls_id in tls_ids}
            occupancies["B1"] = attacked_occupancy + np.random.normal(0, 0.05)
            # Spillback to neighbors
            for neighbor in ["A1", "B0", "B2", "C1"]:
                occupancies[neighbor] += 0.1
        else:
            # Recovery phase
            occupancies = {tls_id: normal_occupancy + np.random.normal(0, 0.05) 
                          for tls_id in tls_ids}
        
        # Clamp occupancies to [0, 1]
        occupancies = {k: max(0.0, min(1.0, v)) for k, v in occupancies.items()}
        
        # Create synthetic phase data
        # B1 stuck in all-red during attack
        phases = {}
        if step < 50 or step >= 100:
            # Normal: phases cycle
            phases = {tls_id: "GGGgrrrrGGGgrrrr" for tls_id in tls_ids}
            # Rotate phase to simulate cycling
            phase_index = (step // 5) % 4
            for tls_id in tls_ids:
                if phase_index == 0:
                    phases[tls_id] = "GGGgrrrrGGGgrrrr"
                elif phase_index == 1:
                    phases[tls_id] = "rrrrrrrrgggGrrrr"
                elif phase_index == 2:
                    phases[tls_id] = "rrrrrrrrgggGrrrr"
                else:
                    phases[tls_id] = "GGGgrrrrGGGgrrrr"
        else:
            # Attack: B1 stuck in all-red
            phases = {tls_id: "GGGgrrrrGGGgrrrr" for tls_id in tls_ids}
            phases["B1"] = "rrrrrrrrrrrrrrrr"  # All red
        
        # Update trust scores
        scorer.update(occupancies, phases)
        
        # Log progress
        if step % 25 == 0 or step == 49 or step == 99:
            logging.info(f"\nStep {step}:")
            if step == 50:
                logging.info("  [ATTACK STARTS]")
            elif step == 100:
                logging.info("  [ATTACK ENDS - RECOVERY BEGINS]")
            
            logging.info(f"  B1 occupancy: {occupancies['B1']:.3f}")
            logging.info(f"  B1 trust score: {scorer.get_trust_score('B1'):.3f}")
            logging.info(f"  B1 suspected: {scorer.is_suspected_compromised('B1')}")
            logging.info(f"  B1 anomalies: {scorer.get_anomaly_signals('B1')}")
        
        # Track results
        results["step"].append(step)
        results["B1_occupancy"].append(occupancies["B1"])
        results["B1_phase"].append(phases["B1"])
        results["B1_trust_score"].append(scorer.get_trust_score("B1"))
        results["B1_suspected"].append(scorer.is_suspected_compromised("B1"))
        results["B1_spillback"].append(scorer.get_anomaly_signals("B1")["spillback"])
        results["B1_phase_lock"].append(scorer.get_anomaly_signals("B1")["phase_lock"])
        results["A1_trust_score"].append(scorer.get_trust_score("A1"))
        results["B0_trust_score"].append(scorer.get_trust_score("B0"))
    
    # Save results
    df = pd.DataFrame(results)
    df.to_csv("trust_scorer_test_results.csv", index=False)
    logging.info("\n\nResults saved to trust_scorer_test_results.csv")
    
    # Print summary
    print("\n" + "=" * 80)
    print("TRUST SCORER TEST SUMMARY")
    print("=" * 80 + "\n")
    
    pre_attack = df[df["step"] < 50]
    attack = df[(df["step"] >= 50) & (df["step"] < 100)]
    recovery = df[df["step"] >= 100]
    
    print("Phase 1: Normal Operation (steps 0-49)")
    print(f"  B1 avg trust score: {pre_attack['B1_trust_score'].mean():.4f}")
    print(f"  B1 avg suspected: {pre_attack['B1_suspected'].mean():.2%}")
    print(f"  A1 avg trust score: {pre_attack['A1_trust_score'].mean():.4f}")
    
    print("\nPhase 2: Attack (steps 50-99)")
    print(f"  B1 avg trust score: {attack['B1_trust_score'].mean():.4f}")
    print(f"  B1 avg suspected: {attack['B1_suspected'].mean():.2%}")
    print(f"  B1 spillback detection: {attack['B1_spillback'].sum()} / {len(attack)} steps")
    print(f"  B1 phase lock detection: {attack['B1_phase_lock'].sum()} / {len(attack)} steps")
    print(f"  A1 avg trust score (neighbor): {attack['A1_trust_score'].mean():.4f}")
    print(f"  B0 avg trust score (neighbor): {attack['B0_trust_score'].mean():.4f}")
    
    print("\nPhase 3: Recovery (steps 100-149)")
    print(f"  B1 avg trust score: {recovery['B1_trust_score'].mean():.4f}")
    print(f"  B1 avg suspected: {recovery['B1_suspected'].mean():.2%}")
    print(f"  A1 avg trust score: {recovery['A1_trust_score'].mean():.4f}")
    
    # Verify expected behavior
    print("\n" + "=" * 80)
    print("VERIFICATION:")
    print("=" * 80)
    
    checks = {
        "Pre-attack B1 trust ≈ 1.0": pre_attack['B1_trust_score'].mean() > 0.95,
        "Attack B1 trust < 0.5": attack['B1_trust_score'].mean() < 0.5,
        "B1 phase lock detected": attack['B1_phase_lock'].sum() > 10,
        "Recovery B1 trust increasing": recovery['B1_trust_score'].mean() > attack['B1_trust_score'].mean(),
    }
    
    for check, passed in checks.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {check}")
    
    all_passed = all(checks.values())
    print(f"\n{'='*80}")
    print(f"Overall: {'✓ ALL TESTS PASSED' if all_passed else '✗ SOME TESTS FAILED'}")
    print(f"{'='*80}")


if __name__ == "__main__":
    test_trust_scorer()
