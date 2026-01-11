"""
Phase 5: Metrics & Analysis

Creates comprehensive visualizations and statistics from cyberattack test results.

Analyzes:
1. Network occupancy over time (pre/post attack)
2. Trust score decay curves (if available)
3. Detection metrics (when attack first detected)
4. Recovery metrics (when network returns to baseline)
5. Comparative statistics across conditions
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, Tuple, Optional


class CyberattackAnalyzer:
    """Analyzes cyberattack test results and generates visualizations."""
    
    def __init__(self, data_file: str, attack_timestep: int = 120):
        """
        Initialize analyzer with test results.
        
        Args:
            data_file: Path to CSV results file
            attack_timestep: Step when attack was triggered
        """
        self.data = pd.read_csv(data_file)
        self.attack_timestep = attack_timestep
        self.analysis_results = {}
        
        print(f"Loaded data from {data_file}")
        print(f"Total steps: {len(self.data)}")
        print(f"Columns: {list(self.data.columns)}\n")
    
    def compute_metrics(self) -> Dict:
        """Compute key metrics from the data."""
        
        pre_attack = self.data[self.data['step'] < self.attack_timestep]
        post_attack = self.data[self.data['step'] >= self.attack_timestep]
        
        metrics = {
            # Occupancy metrics
            'pre_attack_occupancy_mean': pre_attack['network_avg_occupancy'].mean(),
            'post_attack_occupancy_mean': post_attack['network_avg_occupancy'].mean(),
            'occupancy_increase': (post_attack['network_avg_occupancy'].mean() - 
                                  pre_attack['network_avg_occupancy'].mean()),
            'occupancy_increase_pct': ((post_attack['network_avg_occupancy'].mean() - 
                                       pre_attack['network_avg_occupancy'].mean()) / 
                                      pre_attack['network_avg_occupancy'].mean() * 100),
            
            # Attacked TLS metrics
            'pre_attack_b1_occupancy_mean': pre_attack['attacked_occupancy'].mean(),
            'post_attack_b1_occupancy_mean': post_attack['attacked_occupancy'].mean(),
            'b1_occupancy_increase': (post_attack['attacked_occupancy'].mean() - 
                                     pre_attack['attacked_occupancy'].mean()),
            
            # Halted vehicles
            'post_attack_halted_mean': post_attack['attacked_halted_occupancy'].mean(),
        }
        
        # Trust metrics (if available)
        if 'attacked_trust_score' in self.data.columns and self.data['attacked_trust_score'].notna().any():
            pre_trust = pre_attack['attacked_trust_score'].dropna().mean()
            post_trust = post_attack['attacked_trust_score'].dropna().mean()
            metrics['trust_score_pre'] = pre_trust
            metrics['trust_score_post'] = post_trust
            metrics['trust_decay'] = pre_trust - post_trust
        
        self.analysis_results['metrics'] = metrics
        return metrics
    
    def detect_attack(self) -> Dict:
        """
        Detect when attack is first noticed (occupancy spike).
        
        Returns detection metrics like detection_time, magnitude, etc.
        """
        
        pre_attack = self.data[self.data['step'] < self.attack_timestep]
        post_attack = self.data[self.data['step'] >= self.attack_timestep]
        
        baseline_occupancy = pre_attack['network_avg_occupancy'].mean()
        baseline_std = pre_attack['network_avg_occupancy'].std()
        
        # Find first step where occupancy is 2 standard deviations above baseline
        detection_threshold = baseline_occupancy + 2 * baseline_std
        detected = post_attack[post_attack['network_avg_occupancy'] > detection_threshold]
        
        if len(detected) > 0:
            detection_step = detected.iloc[0]['step']
            detection_time = detection_step - self.attack_timestep
            detection_magnitude = detected.iloc[0]['network_avg_occupancy'] - baseline_occupancy
        else:
            detection_step = None
            detection_time = None
            detection_magnitude = None
        
        detection_metrics = {
            'attack_timestep': self.attack_timestep,
            'detection_step': detection_step,
            'detection_time': detection_time,
            'detection_magnitude': detection_magnitude,
            'baseline_occupancy': baseline_occupancy,
            'baseline_std': baseline_std,
            'detection_threshold': detection_threshold,
        }
        
        self.analysis_results['detection'] = detection_metrics
        return detection_metrics
    
    def detect_recovery(self) -> Dict:
        """
        Detect when network recovers (occupancy returns towards baseline).
        
        Returns recovery metrics like recovery_time, final_occupancy, etc.
        """
        
        post_attack = self.data[self.data['step'] >= self.attack_timestep]
        
        if len(post_attack) == 0:
            return {}
        
        baseline_occupancy = self.data[self.data['step'] < self.attack_timestep]['network_avg_occupancy'].mean()
        
        # Recovery = occupancy returns to 1.5x baseline (middle between peak and baseline)
        recovery_target = baseline_occupancy * 1.5
        recovered = post_attack[post_attack['network_avg_occupancy'] < recovery_target]
        
        if len(recovered) > 0:
            recovery_step = recovered.iloc[0]['step']
            recovery_time = recovery_step - self.attack_timestep
            final_occupancy = recovered.iloc[0]['network_avg_occupancy']
        else:
            recovery_step = None
            recovery_time = None
            final_occupancy = post_attack.iloc[-1]['network_avg_occupancy']
        
        recovery_metrics = {
            'recovery_step': recovery_step,
            'recovery_time': recovery_time,
            'final_occupancy': final_occupancy,
            'recovery_target': recovery_target,
        }
        
        self.analysis_results['recovery'] = recovery_metrics
        return recovery_metrics
    
    def plot_occupancy_timeline(self, output_file: str = 'occupancy_timeline.png'):
        """Plot occupancy over time with attack/recovery markers."""
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
        
        # Plot 1: Network occupancy
        ax1.plot(self.data['step'], self.data['network_avg_occupancy'], 
                label='Network Avg Occupancy', linewidth=2, color='steelblue')
        ax1.axvline(self.attack_timestep, color='red', linestyle='--', linewidth=2, 
                   label=f'Attack at step {self.attack_timestep}')
        
        # Add baseline and recovery lines
        pre_attack = self.data[self.data['step'] < self.attack_timestep]
        baseline = pre_attack['network_avg_occupancy'].mean()
        ax1.axhline(baseline, color='green', linestyle=':', linewidth=2, label=f'Baseline: {baseline:.3f}')
        
        ax1.set_xlabel('Simulation Step', fontsize=12)
        ax1.set_ylabel('Network Occupancy', fontsize=12)
        ax1.set_title('Network Occupancy Over Time', fontsize=14, fontweight='bold')
        ax1.legend(fontsize=11)
        ax1.grid(True, alpha=0.3)
        
        # Plot 2: Attacked TLS (B1) occupancy
        ax2.plot(self.data['step'], self.data['attacked_occupancy'], 
                label='B1 (Attacked) Occupancy', linewidth=2, color='crimson')
        ax2.axvline(self.attack_timestep, color='red', linestyle='--', linewidth=2,
                   label=f'Attack at step {self.attack_timestep}')
        
        b1_baseline = pre_attack['attacked_occupancy'].mean()
        ax2.axhline(b1_baseline, color='green', linestyle=':', linewidth=2, 
                   label=f'B1 Baseline: {b1_baseline:.3f}')
        
        ax2.set_xlabel('Simulation Step', fontsize=12)
        ax2.set_ylabel('B1 Occupancy', fontsize=12)
        ax2.set_title('Attacked TLS (B1) Occupancy Over Time', fontsize=14, fontweight='bold')
        ax2.legend(fontsize=11)
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Saved: {output_file}")
        plt.close()
    
    def plot_trust_score(self, output_file: str = 'trust_score_decay.png'):
        """Plot trust score decay over time (if available)."""
        
        if 'attacked_trust_score' not in self.data.columns:
            print("Trust scores not available in data")
            return
        
        if self.data['attacked_trust_score'].isna().all():
            print("Trust scores are all NaN")
            return
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Plot trust score
        valid_trust = self.data[self.data['attacked_trust_score'].notna()]
        ax.plot(valid_trust['step'], valid_trust['attacked_trust_score'], 
               linewidth=2.5, color='purple', label='B1 Trust Score')
        
        # Mark attack
        ax.axvline(self.attack_timestep, color='red', linestyle='--', linewidth=2,
                  label=f'Attack at step {self.attack_timestep}')
        
        # Mark suspected threshold
        ax.axhline(0.5, color='orange', linestyle=':', linewidth=2,
                  label='Suspected Threshold (0.5)')
        
        ax.set_xlabel('Simulation Step', fontsize=12)
        ax.set_ylabel('Trust Score (0-1)', fontsize=12)
        ax.set_title('Trust Score Decay During Attack', fontsize=14, fontweight='bold')
        ax.set_ylim([0, 1.05])
        ax.legend(fontsize=11)
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Saved: {output_file}")
        plt.close()
    
    def plot_pre_post_comparison(self, output_file: str = 'pre_post_comparison.png'):
        """Plot pre/post attack comparison as bar charts."""
        
        pre_attack = self.data[self.data['step'] < self.attack_timestep]
        post_attack = self.data[self.data['step'] >= self.attack_timestep]
        
        metrics = self.analysis_results.get('metrics', {})
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # Network occupancy
        ax = axes[0, 0]
        bars = ax.bar(['Pre-Attack', 'Post-Attack'],
                     [metrics.get('pre_attack_occupancy_mean', 0),
                      metrics.get('post_attack_occupancy_mean', 0)],
                     color=['green', 'red'], alpha=0.7, edgecolor='black', linewidth=2)
        ax.set_ylabel('Occupancy', fontsize=11)
        ax.set_title('Network Occupancy: Pre vs Post Attack', fontsize=12, fontweight='bold')
        ax.set_ylim([0, max(metrics.get('post_attack_occupancy_mean', 0) * 1.2, 0.1)])
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.3f}', ha='center', va='bottom', fontsize=10)
        
        # B1 (Attacked) occupancy
        ax = axes[0, 1]
        bars = ax.bar(['Pre-Attack', 'Post-Attack'],
                     [metrics.get('pre_attack_b1_occupancy_mean', 0),
                      metrics.get('post_attack_b1_occupancy_mean', 0)],
                     color=['steelblue', 'crimson'], alpha=0.7, edgecolor='black', linewidth=2)
        ax.set_ylabel('Occupancy', fontsize=11)
        ax.set_title('B1 (Attacked) Occupancy: Pre vs Post Attack', fontsize=12, fontweight='bold')
        ax.set_ylim([0, max(metrics.get('post_attack_b1_occupancy_mean', 0) * 1.2, 0.1)])
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.3f}', ha='center', va='bottom', fontsize=10)
        
        # Trust score (if available)
        ax = axes[1, 0]
        if 'trust_score_pre' in metrics and 'trust_score_post' in metrics:
            bars = ax.bar(['Pre-Attack', 'Post-Attack'],
                         [metrics['trust_score_pre'], metrics['trust_score_post']],
                         color=['blue', 'purple'], alpha=0.7, edgecolor='black', linewidth=2)
            ax.set_ylabel('Trust Score', fontsize=11)
            ax.set_title('B1 Trust Score: Pre vs Post Attack', fontsize=12, fontweight='bold')
            ax.set_ylim([0, 1.1])
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{height:.3f}', ha='center', va='bottom', fontsize=10)
        else:
            ax.text(0.5, 0.5, 'Trust scores\nnot available', ha='center', va='center',
                   fontsize=12, transform=ax.transAxes)
            ax.axis('off')
        
        # Percentage increase
        ax = axes[1, 1]
        occ_increase_pct = metrics.get('occupancy_increase_pct', 0)
        ax.bar(['Occupancy\nIncrease'], [occ_increase_pct], 
              color='orange', alpha=0.7, edgecolor='black', linewidth=2)
        ax.set_ylabel('Percentage Increase (%)', fontsize=11)
        ax.set_title('Network Occupancy Increase (Attack Impact)', fontsize=12, fontweight='bold')
        ax.set_ylim([0, max(occ_increase_pct * 1.2, 10)])
        ax.text(0, occ_increase_pct, f'{occ_increase_pct:.1f}%', ha='center', va='bottom', fontsize=11)
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Saved: {output_file}")
        plt.close()
    
    def print_summary(self):
        """Print comprehensive analysis summary."""
        
        metrics = self.analysis_results.get('metrics', {})
        detection = self.analysis_results.get('detection', {})
        recovery = self.analysis_results.get('recovery', {})
        
        print("\n" + "=" * 80)
        print("CYBERATTACK ANALYSIS SUMMARY")
        print("=" * 80 + "\n")
        
        print("OCCUPANCY METRICS:")
        print(f"  Pre-attack network occupancy:  {metrics.get('pre_attack_occupancy_mean', 0):.4f}")
        print(f"  Post-attack network occupancy: {metrics.get('post_attack_occupancy_mean', 0):.4f}")
        print(f"  Occupancy increase: +{metrics.get('occupancy_increase', 0):.4f} "
              f"({metrics.get('occupancy_increase_pct', 0):.1f}%)")
        print(f"  B1 pre-attack occupancy:  {metrics.get('pre_attack_b1_occupancy_mean', 0):.4f}")
        print(f"  B1 post-attack occupancy: {metrics.get('post_attack_b1_occupancy_mean', 0):.4f}")
        
        print("\nATTACK DETECTION:")
        print(f"  Attack timestep: {detection.get('attack_timestep', 'N/A')}")
        if detection.get('detection_step') is not None:
            print(f"  Detection step: {detection['detection_step']}")
            print(f"  Detection time: {detection['detection_time']} steps after attack")
            print(f"  Detection magnitude: +{detection['detection_magnitude']:.4f}")
        else:
            print(f"  Detection: No clear spike detected")
        
        print("\nRECOVERY METRICS:")
        if recovery.get('recovery_step') is not None:
            print(f"  Recovery step: {recovery['recovery_step']}")
            print(f"  Recovery time: {recovery['recovery_time']} steps after attack")
            print(f"  Final occupancy: {recovery['final_occupancy']:.4f}")
        else:
            print(f"  Recovery: Network did not recover to target level")
        
        print("\nTRUST SCORE METRICS:")
        if 'trust_score_pre' in metrics:
            print(f"  Pre-attack trust score: {metrics['trust_score_pre']:.4f}")
            print(f"  Post-attack trust score: {metrics['trust_score_post']:.4f}")
            print(f"  Trust decay: {metrics['trust_decay']:.4f}")
        else:
            print(f"  Trust scores: Not available in data")
        
        print("\n" + "=" * 80)


def main():
    """Run analysis on test results."""
    
    # Use the data from test_cyberattack.py
    data_file = "cyberattack_test_results.csv"
    
    if not Path(data_file).exists():
        print(f"Error: {data_file} not found. Run test_cyberattack.py first.")
        return
    
    # Create analyzer
    analyzer = CyberattackAnalyzer(data_file, attack_timestep=120)
    
    # Run analysis
    analyzer.compute_metrics()
    analyzer.detect_attack()
    analyzer.detect_recovery()
    
    # Print summary
    analyzer.print_summary()
    
    # Generate visualizations
    print("\nGenerating visualizations...")
    analyzer.plot_occupancy_timeline("occupancy_timeline.png")
    analyzer.plot_trust_score("trust_score_decay.png")
    analyzer.plot_pre_post_comparison("pre_post_comparison.png")
    
    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
