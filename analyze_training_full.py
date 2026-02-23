import pandas as pd
import numpy as np

base_path = r'F:\Research\networkCA\2026\CyberNet\out\0127\SMARTCOMP\data'

files = {
    'Baseline (No Attack)': f'{base_path}/FedRL/grid-5x5/Cyberattack_5x5_resilience_baseline_naive_ranked.csv',
    'Degraded (Attack, Naive)': f'{base_path}/FedRL/grid-5x5/Cyberattack_5x5_resilience_degraded_naive_ranked.csv',
    'Resilient (Attack, Trust)': f'{base_path}/FedRL/grid-5x5/Cyberattack_5x5_resilience_resilient_trust_ranked.csv',
    'MARL (Multi-Agent)': f'{base_path}/MultiAgent/grid-5x5/Cyberattack_5x5_resilience_multiagent_ranked.csv',
    'SARL (Single-Agent)': f'{base_path}/SingleAgent/grid-5x5/Cyberattack_5x5_resilience_singleagent_ranked.csv'
}

print('=' * 80)
print('TRAINING DATA SUMMARY - 50 EPISODES ANALYSIS')
print('=' * 80)

results = {}
for name, path in files.items():
    df = pd.read_csv(path)
    col = 'episode_reward_mean'
    
    results[name] = {
        'records': len(df),
        'start': df[col].iloc[0],
        'end': df[col].iloc[-1],
        'best': df[col].max(),
        'worst': df[col].min(),
        'improvement': df[col].iloc[-1] - df[col].iloc[0]
    }
    
    print(f'\n{name}:')
    print(f'  Total Records: {len(df)}')
    print(f'  Episode Reward Mean - Start: {df[col].iloc[0]:.2f}')
    print(f'  Episode Reward Mean - End: {df[col].iloc[-1]:.2f}')
    print(f'  Episode Reward Mean - Best: {df[col].max():.2f}')
    print(f'  Episode Reward Mean - Worst: {df[col].min():.2f}')
    print(f'  Improvement (End - Start): {df[col].iloc[-1] - df[col].iloc[0]:.2f}')

# Comparison Table
print('\n' + '=' * 80)
print('COMPARATIVE ANALYSIS TABLE')
print('=' * 80)
print(f'{"Scenario":<30} {"Start":>12} {"End":>12} {"Best":>12} {"Improvement":>14}')
print('-' * 80)
for name, r in results.items():
    print(f'{name:<30} {r["start"]:>12.2f} {r["end"]:>12.2f} {r["best"]:>12.2f} {r["improvement"]:>14.2f}')

# Attack Impact Analysis
print('\n' + '=' * 80)
print('ATTACK IMPACT ANALYSIS')
print('=' * 80)
baseline_end = results['Baseline (No Attack)']['end']
print(f'Baseline Final Reward: {baseline_end:.2f}')
print()
for name in ['Degraded (Attack, Naive)', 'Resilient (Attack, Trust)', 'MARL (Multi-Agent)', 'SARL (Single-Agent)']:
    end = results[name]['end']
    degradation = ((baseline_end - end) / abs(baseline_end)) * 100
    print(f'{name}: {end:.2f} (Degradation: {degradation:.2f}%)')

# Per-Agent Analysis for Final Episode
print('\n' + '=' * 80)
print('PER-AGENT FINAL REWARDS (Last Episode)')
print('=' * 80)

agents = ['A0', 'A1', 'A2', 'B0', 'B1', 'B2', 'C0', 'C1', 'C2']

for name, path in files.items():
    df = pd.read_csv(path)
    print(f'\n{name}:')
    print(f'  {"Agent":<6} {"Final Reward":>14}')
    print('  ' + '-' * 22)
    
    for agent in agents:
        col_name = f'policy_reward_mean/{agent}'
        if col_name in df.columns:
            val = df[col_name].iloc[-1]
            marker = ' ***ATTACKED***' if agent == 'B1' and 'Baseline' not in name else ''
            print(f'  {agent:<6} {val:>14.2f}{marker}')
