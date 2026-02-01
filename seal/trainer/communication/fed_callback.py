from ray.rllib.env import BaseEnv
from ray.rllib.evaluation import MultiAgentEpisode, RolloutWorker
from seal.trainer.communication import *
from seal.trainer.communication.base_callback import BaseCommCallback
from typing import Dict

class FedRLCommCallback(BaseCommCallback):
    '''
    TRAINER:
        * edge2tls_policy += 1 (each fed round)
        * tls2edge_policy += 1 (each fed round)
    ENVIRONMENT:
        * edge2tls_action += 0
        * edge2tls_rank   += 1 (if ranked)
        * tls2edge_obs    += 0
        * veh2tls         += 1 (per vehicle)
    
    TRUST SCORING:
        * Tracks trust_score for each agent (from environment's trust scorer)
        * Stored in episode.user_data["trust_scores"] for trainer access
    '''

    def on_episode_step(self, *, worker: RolloutWorker, base_env: BaseEnv,
                        episode: MultiAgentEpisode, env_index: int, **kwargs) -> None:
        # For some reason, the results of this function return a set of tuples of
        # identical keys... Not sure why, but that's why we only consider the 0th
        # elements of tuples.
        agent_ids = set([tuple[0] for tuple in episode.agent_rewards.keys()])
        for idx in agent_ids:
            info_dict = episode.last_info_for(idx)
            # NOTE: `EDGE2TLS_POLICY` and `TLS2EDGE_POLICY` added in post-processing.
            self.comm_cost[EDGE2TLS_POLICY, idx] += 0
            self.comm_cost[TLS2EDGE_POLICY, idx] += 0
            self.comm_cost[EDGE2TLS_ACTION, idx] += 0
            self.comm_cost[EDGE2TLS_RANK, idx] += int(info_dict["is_ranked"])
            self.comm_cost[TLS2EDGE_OBS, idx] += int(info_dict["is_ranked"])
            self.comm_cost[VEH2TLS_COMM, idx] += info_dict["veh2tls_comms"]
            
            # Track trust scores if available (from environment's trust scorer)
            if "trust_score" in info_dict:
                if "trust_scores" not in episode.user_data:
                    episode.user_data["trust_scores"] = {}
                episode.user_data["trust_scores"][idx] = info_dict["trust_score"]