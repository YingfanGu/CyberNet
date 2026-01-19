import numpy as np

from gym import spaces
from seal.sumo.config import *
from seal.sumo.abstract_env import AbstractSumoEnv
from seal.trust import TrustScorer
from typing import Any, Dict, List, Tuple, Optional


class SumoEnv(AbstractSumoEnv):

    def __init__(self, config):
        # Initialize trust_scorer before calling super().__init__ 
        # because parent's __init__ calls reset()
        self.trust_scorer: Optional[TrustScorer] = None
        self.use_trust_scoring: bool = config.get("use_trust_scoring", False)
        
        super().__init__(config)
        
        # Cyberattack configuration
        self.attack_timestep: Optional[int] = config.get("attack_timestep", None)
        self.attacked_tls_id: Optional[str] = config.get("attacked_tls_id", None)
        self.attack_type: str = config.get("attack_type", "all_red")
        self.attack_triggered = False
        
        # Initialize trust scorer if enabled
        if self.use_trust_scoring:
            self.trust_scorer = TrustScorer(
                tls_graph=self.kernel.tls_hub.tls_graph,
                tls_ids=self.kernel.tls_hub.ids,
                window_size=config.get("trust_window_size", 20),
                spillback_threshold=config.get("trust_spillback_threshold", 0.15),
                phase_lock_threshold=config.get("trust_phase_lock_threshold", 30),
                ema_alpha=config.get("trust_ema_alpha", 0.1),
                suspected_threshold=config.get("trust_suspected_threshold", 0.5)
            )

    def reset(self) -> Any:
        """Reset environment and trust scorer for new episode."""
        if self.trust_scorer is not None:
            self.trust_scorer.reset()
        return super().reset()

    @property
    def multi_action_space(self) -> spaces.Space:
        return spaces.Dict({
            idx: self.kernel.tls_hub[idx].action_space
            for _, idx in self.kernel.tls_hub.index2id.items()
        })

    @property
    def action_space(self) -> spaces.Space:
        """This is the action space defined for a *single* traffic light. It is
           defined this way to support RlLib more easily.

        Returns:
            Space: Action space for a single traffic light.
        """
        first = self.kernel.tls_hub.index2id[0]
        return self.kernel.tls_hub[first].action_space

    @property
    def observation_space(self) -> spaces.Space:
        """This is the observation space defined for a *single* traffic light. It is
           defined this way to support RlLib more easily.

        Returns:
            Space: Observation space for a single traffic light.
        """
        first = self.kernel.tls_hub.index2id[0]
        return self.kernel.tls_hub[first].observation_space

    def action_spaces(self, tls_id) -> spaces.Space:
        return self.kernel.tls_hub[tls_id].action_space

    def observation_spaces(self, tls_id) -> spaces.Space:
        return self.kernel.tls_hub[tls_id].observation_space

    def step(self, action_dict: Dict[Any, int]) -> Tuple[Dict, Dict, Dict, Dict]:
        if action_dict is not None:
            taken_action = self._do_action(action_dict)
        
        # Check if cyberattack should be triggered this step
        self._handle_cyberattack()
        
        self.kernel.step()
        self.step_counter += 1
        obs = self._observe()
        reward = {tls.id: self._get_reward(obs[tls.id])
                  for tls in self.kernel.tls_hub}
        done = {"__all__": self.__get_done()}
        
        # Update trust scores if enabled
        if self.trust_scorer is not None:
            occupancies = {tls.id: obs[tls.id][0] for tls in self.kernel.tls_hub}
            phases = {tls.id: tls.state for tls in self.kernel.tls_hub}
            self.trust_scorer.update(occupancies, phases)
        
        info = {tls.id: {"is_ranked": self.ranked,
                         "veh2tls_comms": tls.get_num_of_controlled_vehicles(),
                         "under_attack": tls.is_under_attack}
                for tls in self.kernel.tls_hub}
        
        # Add trust scores to info if available
        if self.trust_scorer is not None:
            for tls in self.kernel.tls_hub:
                info[tls.id]["trust_score"] = self.trust_scorer.get_trust_score(tls.id)
                info[tls.id]["is_suspected"] = self.trust_scorer.is_suspected_compromised(tls.id)
        
        return obs, reward, done, info

    def _do_action(self, actions: Dict[Any, int]) -> List[int]:
        """Perform the provided action for each trafficlight.

        Args:
            actions (Dict[Any, int]): The action that each trafficlight will take

        Returns:
            Dict[Any, int]: Returns the action taken -- influenced by which moves are
                legal or not.
        """
        taken_action = actions.copy()
        for tls in self.kernel.tls_hub:
            # Skip action if TLS is under attack
            if tls.is_under_attack:
                taken_action[tls.id] = 0
                continue
            
            if self.action_timer.must_change(tls.index) or \
                    (actions[tls.id] == 1 and self.action_timer.can_change(tls.index)):
                tls.next_phase()
                self.action_timer.restart(tls.index)
            else:
                self.action_timer.incr(tls.index)
                taken_action[tls.index] = 0
        return taken_action

    def __get_done(self) -> bool:
        if self.horizon is None:
            return self.kernel.done()
        elif self.step_counter >= self.horizon:
            return True
        else:
            return self.kernel.done()

    def _handle_cyberattack(self) -> None:
        """Check if a cyberattack should be triggered at this timestep.
        
        If attack_timestep matches current step_counter and attacked_tls_id is set,
        trigger the attack on that TLS. Also maintain attack state for TLS under attack.
        """
        # Trigger attack if conditions are met
        if (self.attack_timestep is not None and 
            self.attacked_tls_id is not None and 
            self.step_counter == self.attack_timestep and 
            not self.attack_triggered):
            
            tls_to_attack = self.kernel.tls_hub[self.attacked_tls_id]
            tls_to_attack.force_attack(attack_type=self.attack_type)
            self.attack_triggered = True
        
        # Maintain attack state for all TLS under attack
        for tls in self.kernel.tls_hub:
            if tls.is_under_attack:
                tls.step_under_attack()

    def _get_reward(self, obs: np.ndarray) -> float:
        """Negative reward function based on the number of halting vehicles, waiting time,
           and travel time.

        Parameters
        ----------
        obs : np.ndarray
            Numpy array (containing float64 values) representing the observation.

        Returns
        -------
        float
            The reward for this step
        """
        return -1 * (obs[LANE_OCCUPANCY] + obs[HALTED_LANE_OCCUPANCY])**2  #how to calculate reward

    def _observe(self) -> Dict[Any, np.ndarray]:
        """Get the observations across all the trafficlights, indexed by trafficlight id.

        Returns
        -------
        Dict[Any, np.ndarray]
            Observations from each trafficlight.
        """
        obs = {tls.id: tls.get_observation() for tls in self.kernel.tls_hub}
        if self.ranked:
            self._get_ranks(obs, halted=False)
            self._get_ranks(obs, halted=True)
        # Clean the observation of NaN and (+/-) Inf values.
        for tls in obs:
            for i in range(len(obs[tls])):
                feature = obs[tls][i]
                if feature == np.nan or feature == float('-inf'):
                    obs[tls][i] = 0.0
                elif feature == float('inf'):
                    obs[tls][i] = 1.0
        return obs

    def _get_ranks(self, obs: Dict, halted: bool=False) -> None:
        """Appends global and local ranks to the observations in an inplace fashion.

        Args:
            obs (Dict): Observation provided by a trafficlight.
        """
        if halted:
            pairs = [(tls, tls_state[HALTED_LANE_OCCUPANCY])
                     for tls, tls_state in obs.items()]
            local_index = LOCAL_HALT_RANK
            global_index = GLOBAL_HALT_RANK
        else:
            pairs = [(tls, tls_state[LANE_OCCUPANCY])
                     for tls, tls_state in obs.items()]
            local_index = LOCAL_RANK
            global_index = GLOBAL_RANK
        pairs = sorted(pairs, key=lambda x: x[1], reverse=True)
        graph = self.kernel.tls_hub.tls_graph  # Adjacency list representation.

        # Calculate the GLOBAL ranks for each tls in the road network.
        for global_rank, (tls, _) in enumerate(pairs):
            try:
                obs[tls][global_index] = 1 - (global_rank / (len(graph)-1))
            except ZeroDivisionError:
                obs[tls][global_index] = 1

        # Calculate LOCAL ranks based on global ranks from above.
        for tls in graph:
            local_rank = 0
            for neighbor in graph[tls]:
                if obs[tls][global_index] > obs[neighbor][global_index]:
                    local_rank += 1
            try:
                # We do *not* subtract the denominator by 1 (as we do with global
                # rank) because `len(graph[tls])` does not include `tls` as a
                # node in the sub-network when it should be included. This means that
                # +1 node cancels out the -1 node.
                obs[tls][local_index] = 1 - (local_rank/len(graph[tls]))
            except ZeroDivisionError:
                obs[tls][local_index] = 1
