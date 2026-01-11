from typing import Dict

'''
episode_data = {
    'policy1': {'reward': ..., 'num_vehicles': ...},
    'policy2': {'reward': ..., 'num_vehicles': ...},
    ...
}
'''

def naive_weight_function(episode_data: Dict) -> Dict[str, float]:
    coeffs = {
        policy: 1 / len(episode_data)
        for policy in episode_data
    }
    return coeffs


def neg_reward_weight_function(episode_data: Dict) -> Dict[str, float]:
    total_reward = abs(sum(policy_data["reward"] 
                           for policy_data in episode_data.values()))
    unnormalized_coeffs = {
        policy: total_reward / (policy_data["reward"] - 1)
        for (policy, policy_data) in episode_data.items()
    }
    try:
        coeffs = {
            policy: unnormalized_coeffs[policy] / sum(unnormalized_coeffs.values())
            for policy in episode_data
        }
    except ZeroDivisionError:
        coeffs = naive_weight_function(episode_data)
    return coeffs


def pos_reward_weight_function(episode_data: Dict) -> Dict[str, float]:
    total_reward = sum(policy_data["reward"] 
                       for policy_data in episode_data.values())
    try:
        coeffs = {
            policy: policy_data["reward"] / total_reward
            for (policy, policy_data) in episode_data.items()
        }
    except ZeroDivisionError:
        coeffs = naive_weight_function(episode_data)
    return coeffs


def traffic_weight_function(episode_data: Dict) -> Dict[str, float]:
    total_vehicles = sum(policy_data["num_vehicles"] 
                         for policy_data in episode_data.values())
    try:
        coeffs = {
            policy: policy_data["num_vehicles"] / total_vehicles
            for (policy, policy_data) in episode_data.items()
        }
    except ZeroDivisionError:
        coeffs = naive_weight_function(episode_data)
    return coeffs


def trust_weight_function(episode_data: Dict, trust_scores: Dict[str, float]) -> Dict[str, float]:
    """
    Trust-weighted aggregation: Combine reward-based weighting with trust scores.
    
    Agents with lower trust scores (suspected compromised) get lower weights,
    while trusted agents get higher weights.
    
    Weight formula: w[agent] = (reward[agent] * trust_score[agent]) / sum(...)
    
    Args:
        episode_data: Dict with episode statistics {policy_id: {reward, num_vehicles, ...}}
        trust_scores: Dict with trust scores {policy_id: trust_score} where trust_score in [0,1]
    
    Returns:
        Normalized coefficient dict for weighted aggregation
    """
    # Start with reward-based weights (pos_reward function)
    total_reward = sum(policy_data["reward"] 
                       for policy_data in episode_data.values())
    
    # Weight by reward first
    try:
        reward_weights = {
            policy: policy_data["reward"] / total_reward
            for (policy, policy_data) in episode_data.items()
        }
    except ZeroDivisionError:
        reward_weights = naive_weight_function(episode_data)
    
    # Then modulate by trust score
    trust_adjusted = {}
    for policy in episode_data:
        trust_score = trust_scores.get(policy, 1.0)  # Default to full trust if not provided
        # Combine: higher reward AND higher trust = higher weight
        trust_adjusted[policy] = reward_weights[policy] * trust_score
    
    # Normalize
    total_weight = sum(trust_adjusted.values())
    try:
        coeffs = {
            policy: trust_adjusted[policy] / total_weight
            for policy in episode_data
        }
    except ZeroDivisionError:
        coeffs = naive_weight_function(episode_data)
    
    return coeffs