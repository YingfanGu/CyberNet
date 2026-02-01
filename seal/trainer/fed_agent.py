import numpy as np
import os

from seal.logging import *
from collections import defaultdict
from seal.sumo.env import SumoEnv
from typing import Any, Dict, List, NewType, Optional
from seal.trainer.base import BaseTrainer
from seal.trainer.communication.fed_callback import FedRLCommCallback
from seal.trainer.data.parser import DataParser
from seal.trainer.util import *
from seal.trainer.weight_aggr import *
from time import ctime
from typing import Any, Dict, Tuple

Weights = NewType("Weights", Dict[Any, np.array])
Policy = NewType("Policy", Dict[Any, np.array])


MIN_REWARD = -4
DEFAULT_AGGR_FN = "pos_reward"
WEIGHT_FUNCTIONS = {
    "naive":      naive_weight_function,       # Best (what is used in publication)
    "neg_reward": neg_reward_weight_function,  # BAD
    "pos_reward": pos_reward_weight_function,  # Good
    "traffic":    traffic_weight_function,     # Experimental
    "trust":      "trust_weight_function"      # Trust-weighted (resilience against attacks)
}


class FedPolicyTrainer(BaseTrainer):

    def __init__(self, fed_step: int, **kwargs) -> None:
        super().__init__(
            env=SumoEnv,
            sub_dir="FedRL",
            **kwargs
        )
        self.trainer_name = "FedRL"
        self.fed_step = fed_step
        self.idx = self.get_key_count()
        self.incr_key_count()
        self.policy_config = {}
        self.policy_mapping_fn = lambda agent_id: agent_id
        self.communication_callback_cls = FedRLCommCallback
        self.reward_tracker = defaultdict(float)
        self.episode_data = defaultdict(lambda: defaultdict(float))
        self.weight_fn = kwargs.get("weight_fn", DEFAULT_AGGR_FN)
        assert self.weight_fn in WEIGHT_FUNCTIONS
        
        # Trust scores for resilience against compromised agents
        self.trust_scores: Dict[str, float] = {}
        self.use_trust_weighting: bool = (self.weight_fn == "trust")

    def __reset_reward_tracker(self) -> None:
        for policy in self.reward_tracker:
            self.reward_tracker[policy] = 0.0

    def set_trust_scores(self, trust_scores: Dict[str, float]) -> None:
        """
        Update trust scores for agents (used in trust-weighted aggregation).
        
        Args:
            trust_scores: Dict mapping policy_id to trust_score in [0,1]
        """
        self.trust_scores = trust_scores
    
    def _update_trust_scores_from_env(self) -> None:
        """
        Extract trust scores from the environment's trust scorer.
        
        This bridges the gap between the environment (which computes trust scores)
        and the trainer (which uses them for weighted aggregation).
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Access the environment through the worker
            worker = self.ray_trainer.workers.local_worker()
            env = worker.env
            
            logger.info(f"[TRUST_SCORES] Attempting extraction at round {self._round}")
            logger.info(f"[TRUST_SCORES] env has trust_scorer: {hasattr(env, 'trust_scorer')}")
            
            # Check if environment has trust scorer
            if hasattr(env, 'trust_scorer') and env.trust_scorer is not None:
                self.trust_scores = env.trust_scorer.trust_scores.copy()
                logger.info(f"[TRUST_SCORES] SUCCESS - Extracted {len(self.trust_scores)} scores: {self.trust_scores}")
                
                # Log trust scores for debugging
                suspected = [k for k, v in self.trust_scores.items() if v < 0.7]
                if suspected:
                    logger.warning(f"[TRUST_SCORES] Suspected compromised agents: {suspected}")
            else:
                logger.error(f"[TRUST_SCORES] FAILED - env.trust_scorer not available!")
                # Fallback: try to get from last episode's custom metrics
                if "sampler_results" in self._result:
                    sampler = self._result["sampler_results"]
                    if "custom_metrics" in sampler:
                        # Extract trust scores from episode user_data if available
                        pass  # Trust scores already set via callback
        except Exception as e:
            import logging
            logging.error(f"[TRUST_SCORES] Exception during extraction: {e}", exc_info=True)

    def env_config_fn(self) -> Dict[str, Any]:
        """Override base env_config_fn to include trust scoring if needed."""
        config = super().env_config_fn()
        # Enable trust scoring if using trust-weighted aggregation
        config["use_trust_scoring"] = self.use_trust_weighting
        import logging
        logging.info(f"[ENV_CONFIG] Setting use_trust_scoring={config['use_trust_scoring']}")
        return config

    def on_make_final_policy(self) -> Weights:
        policy_dict = {policy_id: self.ray_trainer.get_policy(policy_id)
                       for policy_id in self.policies
                       if policy_id != GLOBAL_POLICY_VAR}
        return self.fedavg(policy_dict)

    def on_data_recording_step(self) -> None:
        import logging
        logger = logging.getLogger(__name__)
        
        # Determine if aggregation is performed during this training iteration or not.
        aggregate_this_round = self._is_aggregating_step()
        
        logger.info(f"\n[ON_DATA_RECORDING] Round {self._round}, Aggregate={aggregate_this_round}, WeightFn={self.weight_fn}")
        
        # Extract trust scores from the environment if using trust-weighted aggregation
        if self.use_trust_weighting:
            logger.info(f"[ON_DATA_RECORDING] Updating trust scores (use_trust_weighting=True)")
            self._update_trust_scores_from_env()
            logger.info(f"[ON_DATA_RECORDING] After update: trust_scores={self.trust_scores}")
        else:
            logger.info(f"[ON_DATA_RECORDING] Skipping trust score update (use_trust_weighting=False)")

        # Record the data for training process evaluation.
        self.training_data["round"].append(self._round)
        self.training_data["trainer"].append("FedRL")
        self.training_data["fed_round"].append(aggregate_this_round)
        self.training_data["ranked"].append(self.ranked)
        self.training_data["weight_aggr_fn"].append(self.weight_fn)
        for key, value in self._result.items():
            self.training_data[key].append(value)

        # Track the reward for this policy during this training step. This is only
        # used for the FedAvg subroutine in the AGGREGATION step.
        parsed_data = DataParser(self._result)
        for policy in self.policies:
            if policy != GLOBAL_POLICY_VAR:
                self.episode_data[policy]["reward"] += parsed_data.policy_reward(
                    policy)
                self.episode_data[policy]["num_vehicles"] += parsed_data.num_vehicles(
                    policy)
                #
                self.reward_tracker[policy] += \
                    self._result["policy_reward_mean"].get(policy, MIN_REWARD)

        # Aggregate the weights via the Federated Averaging algorithm.
        if aggregate_this_round:
            logger.info(f"[ON_DATA_RECORDING] Performing aggregation this round")
            policy_dict = {policy_id: self.ray_trainer.get_policy(policy_id)
                           for policy_id in self.policies
                           if policy_id != GLOBAL_POLICY_VAR}
            new_params = self.fedavg(policy_dict)
            for policy_id in self.policies:
                self.ray_trainer.get_policy(policy_id).set_weights(new_params)

    '''
    def on_data_recording_step_v1(self) -> None:
        aggregate_this_round = self._is_aggregating_step()
        parsed_data = DataParser(self._result)
        total_reward = 0
        for policy in self.policies:
            # Record the data for training process evaluation.
            self.training_data["round"].append(self._round)
            self.training_data["trainer"].append("FedRL")
            self.training_data["policy"].append(policy)
            self.training_data["fed_round"].append(aggregate_this_round)
            self.training_data["ranked"].append(self.ranked)
            self.training_data["weight_aggr_fn"].append(self.weight_fn)

            for key, value in self._result.items():
                if isinstance(value, dict):
                    if policy in value:
                        self.training_data[key].append(value[policy])
                    else:
                        self.training_data[key].append(value)
                else:
                    self.training_data[key].append(value)

            # Track the reward for this policy during this training step. This is only
            # used for the FedAvg subroutine in the AGGREGATION step.
            if policy != GLOBAL_POLICY_VAR:
                self.episode_data[policy]["reward"] += parsed_data.policy_reward(policy)
                self.episode_data[policy]["num_vehicles"] += parsed_data.num_vehicles(policy)
                #
                self.reward_tracker[policy] += \
                    self._result["policy_reward_mean"].get(policy, MIN_REWARD)

        # Aggregate the weights via the Federated Averaging algorithm.
        if aggregate_this_round:
            policy_dict = {policy_id: self.ray_trainer.get_policy(policy_id)
                           for policy_id in self.policies
                           if policy_id != GLOBAL_POLICY_VAR}
            new_params = self.fedavg(policy_dict)
            for policy_id in self.policies:
                self.ray_trainer.get_policy(policy_id).set_weights(new_params)
    '''

    def on_policy_setup(self) -> Dict[str, Tuple[Any]]:
        dummy_env = self.env(config=self.env_config_fn())
        obs_space = dummy_env.observation_space
        act_space = dummy_env.action_space
        return {
            agent_id: (
                self.policy_type,
                obs_space,
                act_space,
                self.policy_config
            )
            for agent_id in dummy_env._observe()
        }

    def fedavg(
        self,
        policy_dict: Dict[str, Policy]
        # weight_fn: str="traffic"
    ) -> Weights:
        # STEP 1: Grab the aggregation function specified at initialization.
        weight_fn_impl = WEIGHT_FUNCTIONS[self.weight_fn]
        
        # DEBUGGING: Log trust weighting decision
        import logging as py_logging
        logger = py_logging.getLogger(__name__)
        
        logger.info(f"[FEDAVG] Round {self._round}: weight_fn='{self.weight_fn}'")
        logger.info(f"[FEDAVG] trust_scores present: {bool(self.trust_scores)}")
        if self.trust_scores:
            logger.info(f"[FEDAVG] trust_scores: {self.trust_scores}")
        
        # Special handling for trust-weighted aggregation
        if self.weight_fn == "trust" and self.trust_scores:
            # STEP 2a: Compute trust-weighted coefficients
            logger.info(f"[FEDAVG] Using TRUST-WEIGHTED aggregation")
            coeffs = trust_weight_function(self.episode_data, self.trust_scores)
            # Log the weights
            for policy, weight in coeffs.items():
                logger.info(f"[FEDAVG]   {policy}: {weight:.4f}")
        else:
            # STEP 2b: Compute coefficients using standard weight function
            logger.warning(f"[FEDAVG] Using FALLBACK aggregation (trust_scores empty or weight_fn != 'trust')")
            if isinstance(weight_fn_impl, str):
                # Handle string reference (shouldn't happen with current code)
                weight_fn_impl = WEIGHT_FUNCTIONS.get(weight_fn_impl, pos_reward_weight_function)
            coeffs = weight_fn_impl(self.episode_data)
            # Log the weights
            for policy, weight in coeffs.items():
                logger.info(f"[FEDAVG]   {policy}: {weight:.4f}")

        # STEP 3: Compute the reward-based averaged policy weights by weight key.
        new_params = {}
        param_keys = next(iter(policy_dict.values())).get_weights().keys()
        for key in param_keys:
            weights = {policy_id: np.array(policy.get_weights()[key])
                       for policy_id, policy in policy_dict.items()}
            new_params[key] = sum(coeffs[policy_id] * weights[policy_id]
                                  for policy_id in policy_dict)

        # STEP 4: Reset the reward trackers for each of the policies.
        self.__reset_reward_tracker()
        return new_params

    # ============================================================ #

    def on_logging_step(self) -> None:
        aggregate_this_round = self._is_aggregating_step()
        status = "{}Ep. #{} | ranked={} | fed_round={} | Mean reward: {:6.2f} | " \
                 "Mean length: {:4.2f} | Saved {} ({})"
        logging.info(status.format(
            "" if self.trainer_name is None else f"[{self.trainer_name}] ",
            self._round+1,
            self.ranked,
            aggregate_this_round,
            self._result["episode_reward_mean"],
            self._result["episode_len_mean"],
            self.model_path.split(os.sep)[-1],
            ctime()
        ))

    def _is_aggregating_step(self) -> bool:
        if self.fed_step is None:
            return True
        elif (self._round + 1) % self.fed_step == 0:
            return True
        else:
            return False
