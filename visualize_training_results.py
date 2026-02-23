import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

base_path = r'F:\Research\networkCA\2026\CyberNet\out\SMARTCOMP\data'

files = {
    'Baseline (No Attack)': f'{base_path}/FedRL/grid-5x5/Cyberattack_5x5_resilience_baseline_naive_ranked.csv',
    'Degraded (Attack, Naive)': f'{base_path}/FedRL/grid-5x5/Cyberattack_5x5_resilience_degraded_naive_ranked.csv',
    'Resilient (Attack, Trust)': f'{base_path}/FedRL/grid-5x5/Cyberattack_5x5_resilience_resilient_trust_ranked.csv',
    'MARL (Multi-Agent)': f'{base_path}/MARL/grid-5x5/Cyberattack_5x5_resilience_multiagent_ranked.csv',
    'SARL (Single-Agent)': f'{base_path}/SARL/grid-5x5/Cyberattack_5x5_resilience_singleagent_ranked.csv'
}

colors = {
    'Baseline (No Attack)': '#2ecc71',  # Green
    'Degraded (Attack, Naive)': '#3498db',  # Blue
    'Resilient (Attack, Trust)': '#e74c3c',  # Red
    'MARL (Multi-Agent)': '#9b59b6',  # Purple
    'SARL (Single-Agent)': '#f39c12'  # Orange
}

# Load all data
dfs = {name: pd.read_csv(path) for name, path in files.items()}

# Create figure with subplots
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Training Analysis - 50 Episodes (FedRL vs MARL vs SARL under Cyberattack)', fontsize=14, fontweight='bold')

# Plot 1: Learning Curves (Episode Reward Mean)
ax1 = axes[0, 0]
for name, df in dfs.items():
    ax1.plot(df['round'], df['episode_reward_mean'], label=name, color=colors[name], linewidth=2)
ax1.set_xlabel('Training Round')
ax1.set_ylabel('Episode Reward Mean')
ax1.set_title('Learning Curves - All Scenarios')
ax1.legend(loc='best', fontsize=8)
ax1.grid(True, alpha=0.3)
#ax1.axhline(y=-650.70, color='gray', linestyle='--', alpha=0.5, label='Baseline Final')

ax1.axhline(y=-3000, color='gray', linestyle='--', alpha=0.5, label='Baseline Final')


# Plot 2: FedRL Comparison (Baseline vs Degraded vs Resilient)
ax2 = axes[0, 1]
fedrl_scenarios = ['Baseline (No Attack)', 'Degraded (Attack, Naive)', 'Resilient (Attack, Trust)']
for name in fedrl_scenarios:
    df = dfs[name]
    ax2.plot(df['round'], df['episode_reward_mean'], label=name, color=colors[name], linewidth=2)
ax2.set_xlabel('Training Round')
ax2.set_ylabel('Episode Reward Mean')
ax2.set_title('FedRL: Baseline vs Attack Scenarios')
ax2.legend(loc='best', fontsize=8)
ax2.grid(True, alpha=0.3)

# Plot 3: Bar chart - Final Performance
ax3 = axes[1, 0]
final_rewards = {name: df['episode_reward_mean'].iloc[-1] for name, df in dfs.items()}
best_rewards = {name: df['episode_reward_mean'].max() for name, df in dfs.items()}

x = np.arange(len(final_rewards))
width = 0.35

bars1 = ax3.bar(x - width/2, list(final_rewards.values()), width, label='Final Reward', color=[colors[n] for n in final_rewards.keys()])
bars2 = ax3.bar(x + width/2, list(best_rewards.values()), width, label='Best Reward', color=[colors[n] for n in final_rewards.keys()], alpha=0.5)

ax3.set_ylabel('Episode Reward Mean')
ax3.set_title('Final vs Best Performance')
ax3.set_xticks(x)
ax3.set_xticklabels(['Baseline', 'Degraded', 'Resilient', 'MARL', 'SARL'], rotation=15, ha='right')
ax3.legend()
ax3.grid(True, alpha=0.3, axis='y')

# Plot 4: Degradation from Baseline
ax4 = axes[1, 1]
baseline_final = final_rewards['Baseline (No Attack)']
degradation = {name: ((baseline_final - val) / abs(baseline_final)) * 100 
               for name, val in final_rewards.items() if name != 'Baseline (No Attack)'}

bars = ax4.bar(range(len(degradation)), list(degradation.values()), 
               color=[colors[n] for n in degradation.keys()])
ax4.set_ylabel('Degradation from Baseline (%)')
ax4.set_title('Performance Degradation Under Attack')
ax4.set_xticks(range(len(degradation)))
ax4.set_xticklabels(['Degraded\n(Naive)', 'Resilient\n(Trust)', 'MARL', 'SARL'], rotation=0)
ax4.grid(True, alpha=0.3, axis='y')

# Add value labels on bars
for bar, val in zip(bars, degradation.values()):
    ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, 
             f'{val:.1f}%', ha='center', va='bottom', fontsize=10)

plt.tight_layout()
plt.savefig(r'F:\Research\networkCA\2026\CyberNet\out\SMARTCOMP\training_analysis_50ep.png', dpi=150, bbox_inches='tight')
plt.show()

print("Figure saved to: out/0127/SMARTCOMP/training_analysis_50ep.png")

# Print detailed statistics
print('\n' + '=' * 80)
print('DETAILED STATISTICS')
print('=' * 80)
print(f'\n{"Metric":<40} {"Baseline":>10} {"Degraded":>10} {"Resilient":>10} {"MARL":>10} {"SARL":>10}')
print('-' * 100)

metrics = ['episode_reward_mean', 'episode_reward_max', 'episode_reward_min']
for metric in metrics:
    row = f'{metric:<40}'
    for name in dfs.keys():
        val = dfs[name][metric].iloc[-1]
        row += f'{val:>10.2f}'
    print(row)

print('\n' + '=' * 80)
print('KEY FINDINGS')
print('=' * 80)
print("""
1. BASELINE (No Attack): Best performance with continuous improvement
   - Final: -650.70, Improved by +26.31 over training

2. DEGRADED (Attack + Naive Aggregation): Second best under attack
   - Final: -677.12, 4.06% degradation from baseline
   - Still showed positive learning (+22.64)

3. RESILIENT (Attack + Trust Aggregation): UNDERPERFORMED!
   - Final: -729.43, 12.10% degradation from baseline
   - NEGATIVE learning trend (-29.67) - got worse over training!
   
4. MARL (Multi-Agent, No Federation): Worst performance
   - Final: -759.62, 16.74% degradation
   - Severe negative learning (-59.86)

5. SARL (Single-Agent): Also poor
   - Final: -742.69, 14.14% degradation
   - Negative learning (-27.57)

CRITICAL INSIGHT:
The trust-weighted aggregation is HARMING performance compared to naive aggregation!
Trust mechanism needs further tuning or there may be a bug in implementation.
""")
