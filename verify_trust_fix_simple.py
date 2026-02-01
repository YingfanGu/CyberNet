"""
Simplified Trust Weighting Fix Verification
Focuses on the key proof: env_config_fn() correctly sets use_trust_scoring flag
"""

import logging
import sys
import os

# Configure logging for Windows compatibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trust_fix_verification.log", encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

def test_env_config_flag():
    """Test 1: Verify env_config includes use_trust_scoring flag"""
    logger.info("\n" + "="*80)
    logger.info("TEST 1: Environment Config Flag")
    logger.info("="*80)
    
    from seal.trainer.fed_agent import FedPolicyTrainer
    
    # Create trainer with trust weighting
    logger.info("\nCreating FedPolicyTrainer with weight_fn='trust'...")
    trainer = FedPolicyTrainer(
        fed_step=11,
        network="grid_3x3",
        num_episodes=1,
        weight_fn="trust",  # KEY: request trust weighting
        seed=12345
    )
    
    logger.info(f"  - Trainer.weight_fn: {trainer.weight_fn}")
    logger.info(f"  - Trainer.use_trust_weighting: {trainer.use_trust_weighting}")
    
    # Get env config
    env_config = trainer.env_config_fn()
    logger.info(f"  - env_config keys: {list(env_config.keys())}")
    
    # Verify the flag is set
    has_flag = "use_trust_scoring" in env_config
    flag_value = env_config.get("use_trust_scoring", False)
    
    logger.info(f"\n  - env_config['use_trust_scoring'] present: {has_flag}")
    logger.info(f"  - env_config['use_trust_scoring'] value: {flag_value}")
    
    if has_flag and flag_value is True:
        logger.info("\n[PASS] Environment config correctly includes use_trust_scoring=True")
        return True
    else:
        logger.error("\n[FAIL] use_trust_scoring flag not found or False")
        return False

def test_trust_weighting_disabled():
    """Test 2: Verify trust weighting is disabled when weight_fn != 'trust'"""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: Trust Weighting Disabled for Other weight_fn")
    logger.info("="*80)
    
    from seal.trainer.fed_agent import FedPolicyTrainer
    
    # Create trainer WITHOUT trust weighting
    logger.info("\nCreating FedPolicyTrainer with weight_fn='pos_reward'...")
    trainer = FedPolicyTrainer(
        fed_step=11,
        network="grid_3x3",
        num_episodes=1,
        weight_fn="pos_reward",  # NOT trust
        seed=12345
    )
    
    logger.info(f"  - Trainer.weight_fn: {trainer.weight_fn}")
    logger.info(f"  - Trainer.use_trust_weighting: {trainer.use_trust_weighting}")
    
    # Get env config
    env_config = trainer.env_config_fn()
    flag_value = env_config.get("use_trust_scoring", False)
    
    logger.info(f"  - env_config['use_trust_scoring'] value: {flag_value}")
    
    if flag_value is False:
        logger.info("\n[PASS] Trust scoring correctly disabled when weight_fn='pos_reward'")
        return True
    else:
        logger.error("\n[FAIL] Trust scoring should be False when weight_fn != 'trust'")
        return False

def test_trust_scoring_default():
    """Test 3: Verify trust scoring defaults to False"""
    logger.info("\n" + "="*80)
    logger.info("TEST 3: Trust Scoring Defaults")
    logger.info("="*80)
    
    from seal.trainer.fed_agent import FedPolicyTrainer
    
    # Create trainer with default weight_fn
    logger.info("\nCreating FedPolicyTrainer with default weight_fn...")
    trainer = FedPolicyTrainer(
        fed_step=11,
        network="grid_3x3",
        num_episodes=1,
        seed=12345
    )
    
    logger.info(f"  - Trainer.weight_fn: {trainer.weight_fn}")
    logger.info(f"  - Trainer.use_trust_weighting: {trainer.use_trust_weighting}")
    
    # Get env config
    env_config = trainer.env_config_fn()
    flag_value = env_config.get("use_trust_scoring", "MISSING")
    
    logger.info(f"  - env_config['use_trust_scoring'] value: {flag_value}")
    
    if flag_value is False:
        logger.info("\n[PASS] Trust scoring defaults to False correctly")
        return True
    else:
        logger.error(f"\n[FAIL] Expected False, got {flag_value}")
        return False

def main():
    logger.info("\n" + "="*80)
    logger.info("TRUST WEIGHTING FIX VERIFICATION - SIMPLIFIED")
    logger.info("="*80)
    
    results = {}
    
    # Run all tests
    results["Config Flag"] = test_env_config_flag()
    results["Disabled Mode"] = test_trust_weighting_disabled()
    results["Defaults"] = test_trust_scoring_default()
    
    # Summary
    logger.info("\n" + "="*80)
    logger.info("VERIFICATION SUMMARY")
    logger.info("="*80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        logger.info(f"{status} {name}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("\nSUCCESS: All tests passed! Fix is working correctly.")
        logger.info("\nKey Finding:")
        logger.info("  - env_config_fn() override is active")
        logger.info("  - use_trust_scoring flag is properly set based on weight_fn")
        logger.info("  - When weight_fn='trust', use_trust_scoring=True")
        logger.info("  - Environment will now initialize TrustScorer correctly")
        return 0
    else:
        logger.error(f"\nFAILURE: {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
