"""
Test script to verify trust score extraction and weighting during training.
Runs a single training iteration with detailed logging.
"""

import logging
import sys

# Configure logging to print everything
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trust_logging_test.log")
    ]
)

logger = logging.getLogger(__name__)

logger.info("=" * 80)
logger.info("STARTING TRUST WEIGHTING LOGGING TEST")
logger.info("=" * 80)

# Import trainer
from seal.trainer.fed_agent import FedPolicyTrainer

# Create trainer with trust-weighted aggregation
logger.info("\nCreating FedPolicyTrainer with weight_fn='trust'...")
trainer = FedPolicyTrainer(
    fed_step=11,
    network="grid_3x3",
    num_episodes=2,  # Just 2 episodes for testing
    weight_fn="trust",  # THIS IS KEY - test trust weighting
    seed=12345,
    run_name="trust_logging_test"
)

logger.info(f"Trainer created:")
logger.info(f"  - use_trust_weighting: {trainer.use_trust_weighting}")
logger.info(f"  - weight_fn: {trainer.weight_fn}")
logger.info(f"  - Fed_Callback initialized: {trainer.fed_callback is not None}")

# Run training
logger.info("\n" + "=" * 80)
logger.info("STARTING TRAINING RUN")
logger.info("=" * 80 + "\n")

try:
    results = trainer.train()
    
    logger.info("\n" + "=" * 80)
    logger.info("TRAINING COMPLETED SUCCESSFULLY")
    logger.info("=" * 80)
    logger.info(f"\nFinal Results:")
    logger.info(f"  Episodes trained: {results.get('episodes_total', 'N/A')}")
    logger.info(f"  Total timesteps: {results.get('timesteps_total', 'N/A')}")
    
except Exception as e:
    logger.error("\n" + "=" * 80)
    logger.error("TRAINING FAILED WITH EXCEPTION")
    logger.error("=" * 80)
    logger.error(f"Error: {e}", exc_info=True)
    sys.exit(1)

logger.info("\nLogging test complete. Check trust_logging_test.log for full output.")
logger.info("Look for '[TRUST_SCORES]' and '[FEDAVG]' log entries to verify trust weighting.")
