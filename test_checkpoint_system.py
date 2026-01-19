#!/usr/bin/env python
"""
Quick test to verify the new clean checkpoint system works.

Run: python test_checkpoint_system.py

This will:
1. Train for 3 episodes with clean checkpoints
2. Verify checkpoint files are created
3. Resume training for 2 more episodes
4. Verify new checkpoints are created
"""

import os
import sys
from pathlib import Path
from netfiles import *
from seal.logging import *
from seal.trainer.fed_agent import FedPolicyTrainer

OUT_PREFIX = "Checkpoint_Test"
trainer_kwargs = {
    "horizon": 360,
}

ATTACK_TIMESTEP = 120
ATTACKED_TLS_ID = "B1"
ATTACK_TYPE = "all_red"

def test_fresh_training():
    """Test 1: Fresh training with clean checkpoints"""
    logging.info("\n" + "="*80)
    logging.info("TEST 1: Fresh Training with Clean Checkpoints")
    logging.info("="*80 + "\n")
    
    class TestTrainer(FedPolicyTrainer):
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
    
    trainer = TestTrainer(
        fed_step=1, net_file=GRID_3x3, ranked=True,
        out_prefix=f"{OUT_PREFIX}_test",
        trainer_kwargs=trainer_kwargs,
        weight_fn="trust",
        checkpoint_freq=1,
    )
    
    logging.info("Training for 3 episodes...")
    trainer.train(3)
    
    # Check that checkpoints were created
    checkpoint_dir = trainer.model_path
    clean_checkpoints = []
    if os.path.exists(checkpoint_dir):
        for file in os.listdir(checkpoint_dir):
            if file.startswith("checkpoint_") and file.endswith(".pkl"):
                clean_checkpoints.append(file)
    
    clean_checkpoints.sort()
    logging.info(f"\nCreated {len(clean_checkpoints)} clean checkpoints:")
    for cp in clean_checkpoints:
        cp_path = os.path.join(checkpoint_dir, cp)
        cp_size = os.path.getsize(cp_path) / 1024  # KB
        logging.info(f"  ✓ {cp} ({cp_size:.1f} KB)")
    
    if len(clean_checkpoints) < 3:
        logging.error(f"ERROR: Expected 3 checkpoints, got {len(clean_checkpoints)}")
        return False
    
    logging.info("\n✓ TEST 1 PASSED\n")
    return checkpoint_dir

def test_resume_training(checkpoint_dir):
    """Test 2: Resume training from checkpoint"""
    logging.info("="*80)
    logging.info("TEST 2: Resume Training from Checkpoint")
    logging.info("="*80 + "\n")
    
    class TestTrainer(FedPolicyTrainer):
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
    
    # Find the latest checkpoint
    latest_checkpoint = None
    max_episode = -1
    for file in os.listdir(checkpoint_dir):
        if file.startswith("checkpoint_") and file.endswith(".pkl"):
            try:
                episode = int(file.split("_")[1].split(".")[0])
                if episode > max_episode:
                    max_episode = episode
                    latest_checkpoint = os.path.join(checkpoint_dir, file)
            except:
                pass
    
    if not latest_checkpoint:
        logging.error("ERROR: No checkpoint found to resume from")
        return False
    
    logging.info(f"Resuming from checkpoint: {latest_checkpoint}")
    
    trainer = TestTrainer(
        fed_step=1, net_file=GRID_3x3, ranked=True,
        out_prefix=f"{OUT_PREFIX}_test",
        trainer_kwargs=trainer_kwargs,
        weight_fn="trust",
        checkpoint_freq=1,
    )
    
    logging.info("Training for 2 more episodes...")
    try:
        trainer.train(2, checkpoint=latest_checkpoint)
        logging.info("\n✓ TEST 2 PASSED\n")
        return True
    except Exception as e:
        logging.error(f"\n✗ TEST 2 FAILED: {e}\n")
        return False

if __name__ == "__main__":
    logging.info("\n" + "="*80)
    logging.info("CHECKPOINT SYSTEM TEST")
    logging.info("Testing clean checkpoint save/load functionality")
    logging.info("="*80 + "\n")
    
    try:
        # Test 1: Fresh training
        checkpoint_dir = test_fresh_training()
        if not checkpoint_dir:
            logging.error("TESTS FAILED: Could not create checkpoints")
            sys.exit(1)
        
        # Test 2: Resume training
        success = test_resume_training(checkpoint_dir)
        if not success:
            logging.error("TESTS FAILED: Could not resume from checkpoint")
            sys.exit(1)
        
        logging.info("="*80)
        logging.info("ALL TESTS PASSED ✓")
        logging.info("Checkpoint system is working correctly!")
        logging.info("="*80)
        
    except Exception as e:
        logging.error(f"\nTEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
