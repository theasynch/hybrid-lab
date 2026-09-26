"""
End-to-End Assay Simulator
============================

Stitches together all biological domain models into a complete
LAMP → CRISPR → Fluorescence simulation pipeline.

Architecture (from Simulation Plan, Section 2):

    BIOLOGICAL DOMAIN
    ┌─────────────────────────────┐
    │ Target DNA/RNA sequence     │
    │         ↓                   │
    │ LAMP amplification model    │
    │         ↓                   │
    │ Cas12a recognition model    │
    │         ↓                   │
    │ Reporter cleavage           │
    │         ↓                   │
    │ Virtual fluorescence F(t)   │
    └─────────────┬───────────────┘
                  │
                  ↓
           SENSOR DOMAIN (Phase 2)

This simulator connects:
    1. thermal_model → temperature profiles
    2. lamp_model → amplification kinetics (temperature-dependent)
    3. crispr_model → Cas12a activation + reporter cleavage
    4. fluorescence_model → virtual fluorescence signal

It produces the complete fluorescence curve that will later feed
into the RTL testbench as virtual ADC data.
"""

import sys
import os
import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import Optional
from scipy.interpolate import interp1d

# Ensure biology package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from biology.lamp_model import LAMPParameters, simulate_lamp
from biology.crispr_model import CRISPRParameters, simulate_crispr
from biology.fluorescence_model import (
    FluorescenceParameters, generate_fluorescence
)
from biology.thermal_model import (
    ThermalParameters, PIDParameters, simulate_thermal_profile,
    create_lamp_crispr_schedule
)


@dataclass
class AssayConfiguration:
    """Complete assay configuration.
    
    Attributes:
        name: Assay identifier string.
        lamp_duration_min: LAMP amplification duration (minutes).
        crispr_duration_min: CRISPR incubation duration (minutes).
        lamp_temp: LAMP reaction temperature (°C).
        crispr_temp: CRISPR incubation temperature (°C).
        transfer_fraction: Fraction of amplicon transferred to CRISPR chamber.
        target_present: Whether target DNA/RNA is present.
        target_concentration: Relative concentration (0–1).
                             1.0 = high copy number, 0.01 = near LoD.
    """
    name: str = "HYBRID-LAB Assay v1"
    lamp_duration_min: float = 30.0
    crispr_duration_min: float = 15.0
    lamp_temp: float = 63.0
    crispr_temp: float = 37.0
    transfer_fraction: float = 0.5
    target_present: bool = True
    target_concentration: float = 1.0


def run_assay(config: Optional[AssayConfiguration] = None,
              lamp_params: Optional[LAMPParameters] = None,
              crispr_params: Optional[CRISPRParameters] = None,
              fluo_params: Optional[FluorescenceParameters] = None,
              thermal_params: Optional[ThermalParameters] = None,
              pid_params: Optional[PIDParameters] = None,
              add_noise: bool = True,
              rng_seed: Optional[int] = None,
              ) -> dict:
    """Run the complete assay simulation.
    
    This executes the full pipeline:
        thermal profile → LAMP → transfer → CRISPR → fluorescence
    
    Args:
        config: Assay configuration.
        lamp_params: LAMP model parameters (uses defaults if None).
        crispr_params: CRISPR model parameters.
        fluo_params: Fluorescence model parameters.
        thermal_params: Thermal model parameters.
        pid_params: PID controller parameters.
        add_noise: Whether to add measurement noise.
        rng_seed: Random seed for reproducibility.
    
    Returns:
        Dictionary containing all simulation results from each domain,
        plus the unified timeline.
    """
    if config is None:
        config = AssayConfiguration()
    if lamp_params is None:
        lamp_params = LAMPParameters()
    if crispr_params is None:
        crispr_params = CRISPRParameters()
    if fluo_params is None:
        fluo_params = FluorescenceParameters()
    if thermal_params is None:
        thermal_params = ThermalParameters()
    if pid_params is None:
        pid_params = PIDParameters()
    
    # ── Step 1: Thermal Profile ──────────────────────────────────────
    schedule = create_lamp_crispr_schedule(
        lamp_temp=config.lamp_temp,
        lamp_duration_min=config.lamp_duration_min,
        crispr_temp=config.crispr_temp,
        crispr_duration_min=config.crispr_duration_min,
    )
    
    total_time_s = (config.lamp_duration_min + config.crispr_duration_min + 5) * 60
    
    thermal_result = simulate_thermal_profile(
        setpoint_schedule=schedule,
        thermal_params=thermal_params,
        pid_params=pid_params,
        dt=0.5,
        total_time=total_time_s,
    )
    
    # Create temperature interpolation function for LAMP
    T_interp = interp1d(thermal_result['t'], thermal_result['T'],
                         kind='linear', fill_value='extrapolate')
    
    def T_lamp(t_min):
        """Temperature during LAMP phase (input in minutes)."""
        return float(T_interp(t_min * 60.0))
    
    # ── Step 2: LAMP Amplification ───────────────────────────────────
    # Scale initial seed by target concentration
    if config.target_present:
        lamp_params_run = LAMPParameters(
            k_a=lamp_params.k_a,
            A_max=lamp_params.A_max,
            T_opt=lamp_params.T_opt,
            sigma_T=lamp_params.sigma_T,
            A_0_positive=lamp_params.A_0_positive * config.target_concentration,
            A_0_negative=lamp_params.A_0_negative,
            lag_time=lamp_params.lag_time,
        )
    else:
        lamp_params_run = lamp_params
    
    lamp_result = simulate_lamp(
        params=lamp_params_run,
        target_present=config.target_present,
        T_func=T_lamp,
        t_span=(0.0, config.lamp_duration_min),
    )
    
    # ── Step 3: Amplicon Transfer ────────────────────────────────────
    # The final LAMP product, scaled by transfer fraction
    A_transferred = lamp_result['A'][-1] * config.transfer_fraction
    
    # ── Step 4: CRISPR-Cas12a Detection ──────────────────────────────
    # Temperature function for CRISPR phase
    lamp_end_s = config.lamp_duration_min * 60.0
    
    def T_crispr(t_min):
        """Temperature during CRISPR phase."""
        return float(T_interp(lamp_end_s + t_min * 60.0))
    
    crispr_result = simulate_crispr(
        params=crispr_params,
        A_func=lambda t: A_transferred,  # constant transferred amplicon
        T_func=T_crispr,
        t_span=(0.0, config.crispr_duration_min),
    )
    
    # ── Step 5: Fluorescence Signal ──────────────────────────────────
    fluo_result = generate_fluorescence(
        crispr_result['t'],
        crispr_result['R'],
        R_0=crispr_params.R_0,
        params=fluo_params,
        add_noise=add_noise,
        rng_seed=rng_seed,
    )
    
    # ── Build Unified Timeline ───────────────────────────────────────
    # LAMP runs from t=0 to t=lamp_duration
    # CRISPR runs from t=lamp_duration to t=lamp_duration+crispr_duration
    
    t_unified_lamp = lamp_result['t']
    t_unified_crispr = config.lamp_duration_min + crispr_result['t']
    t_unified = np.concatenate([t_unified_lamp, t_unified_crispr])
    
    return {
        'config': config,
        'thermal': thermal_result,
        'lamp': lamp_result,
        'crispr': crispr_result,
        'fluorescence': fluo_result,
        'transfer': {
            'A_final_lamp': lamp_result['A'][-1],
            'A_transferred': A_transferred,
            'fraction': config.transfer_fraction,
        },
        'timeline': {
            't_lamp': t_unified_lamp,
            't_crispr': t_unified_crispr,
            't_unified': t_unified,
            'lamp_end_min': config.lamp_duration_min,
            'crispr_end_min': config.lamp_duration_min + config.crispr_duration_min,
        },
    }


def classify_result(fluo_result: dict,
                    threshold_positive: float = 0.5,
                    threshold_negative: float = 0.2,
                    control_valid: bool = True,
                    ) -> str:
    """Classify assay result (Eq. 11 from the paper).
    
    Decision rule:
        POSITIVE:      F_N(t_f) ≥ θ_p  AND  control valid
        NEGATIVE:      F_N(t_f) < θ_n  AND  control valid
        INDETERMINATE: θ_n ≤ F_N(t_f) < θ_p  AND  control valid
        INVALID:       control NOT valid
    
    Args:
        fluo_result: Fluorescence results from generate_fluorescence().
        threshold_positive: θ_p threshold.
        threshold_negative: θ_n threshold.
        control_valid: Whether control reactions passed.
    
    Returns:
        Classification string.
    """
    if not control_valid:
        return "INVALID"
    
    # Use the final noisy fluorescence value
    F_final = fluo_result['F_noisy'][-1]
    F_baseline = fluo_result['F_noisy'][0]  # first few samples
    
    # Simple endpoint metric
    delta_F = F_final - F_baseline
    
    if delta_F >= threshold_positive:
        return "POSITIVE"
    elif delta_F < threshold_negative:
        return "NEGATIVE"
    else:
        return "INDETERMINATE"


def plot_assay_results(result: dict, save_path: Optional[str] = None):
    """Create comprehensive visualization of assay results.
    
    Generates a 2×2 figure showing:
        1. Thermal profile with phase annotations
        2. LAMP amplification curve
        3. CRISPR reporter cleavage
        4. Final fluorescence signal with threshold
    """
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(
        f"HYBRID-LAB Digital Twin — {result['config'].name}\n"
        f"Target: {'PRESENT' if result['config'].target_present else 'ABSENT'} "
        f"(conc={result['config'].target_concentration:.3f})",
        fontsize=15, fontweight='bold'
    )
    
    config = result['config']
    lamp_end = config.lamp_duration_min
    crispr_end = lamp_end + config.crispr_duration_min
    
    # ── 1. Thermal Profile ───────────────────────────────────────────
    ax = axes[0, 0]
    t_min = result['thermal']['t_min']
    mask = t_min <= crispr_end + 2
    ax.plot(t_min[mask], result['thermal']['T'][mask],
            linewidth=2, color='#e74c3c', label='Chamber T')
    ax.plot(t_min[mask], result['thermal']['setpoint'][mask],
            linewidth=2, color='#3498db', linestyle='--', label='Setpoint')
    ax.axvline(lamp_end, color='gray', linestyle=':', alpha=0.7)
    ax.axvspan(0, lamp_end, alpha=0.05, color='green')
    ax.axvspan(lamp_end, crispr_end, alpha=0.05, color='blue')
    ax.text(lamp_end / 2, 28, 'LAMP', ha='center', fontsize=11,
            style='italic', color='green')
    ax.text(lamp_end + config.crispr_duration_min / 2, 28, 'CRISPR',
            ha='center', fontsize=11, style='italic', color='blue')
    ax.set_ylabel('Temperature (°C)', fontsize=11)
    ax.set_title('Thermal Profile', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    # ── 2. LAMP Amplification ────────────────────────────────────────
    ax = axes[0, 1]
    ax.plot(result['lamp']['t'], result['lamp']['A'],
            linewidth=2.5, color='#2ecc71')
    ax.axhline(y=result['transfer']['A_transferred'], color='#f39c12',
               linestyle='--', alpha=0.7,
               label=f"Transferred: {result['transfer']['A_transferred']:.3f}")
    ax.set_ylabel('Amplified Product A(t)', fontsize=11)
    ax.set_title('LAMP Amplification', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xlabel('Time (min)', fontsize=11)
    
    # ── 3. CRISPR Reporter Cleavage ──────────────────────────────────
    ax = axes[1, 0]
    ax.plot(result['crispr']['t'], result['crispr']['R'],
            linewidth=2, color='#9b59b6', label='Intact Reporter')
    ax.plot(result['crispr']['t'], result['crispr']['C_active'],
            linewidth=2, color='#e67e22', label='Active Cas12a')
    ax.set_xlabel('CRISPR Incubation (min)', fontsize=11)
    ax.set_ylabel('Concentration', fontsize=11)
    ax.set_title('Cas12a Detection Stage', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    # ── 4. Fluorescence Signal ───────────────────────────────────────
    ax = axes[1, 1]
    fluo = result['fluorescence']
    ax.plot(result['crispr']['t'], fluo['F_ideal'],
            linewidth=2, color='#2ecc71', label='Ideal F(t)', alpha=0.6)
    ax.plot(result['crispr']['t'], fluo['F_noisy'],
            linewidth=1.5, color='#3498db', label='Measured F(t)')
    
    # Classification
    classification = classify_result(fluo)
    color_map = {
        'POSITIVE': '#2ecc71', 'NEGATIVE': '#e74c3c',
        'INDETERMINATE': '#f39c12', 'INVALID': '#95a5a6'
    }
    ax.text(0.98, 0.95, classification, transform=ax.transAxes,
            fontsize=16, fontweight='bold', ha='right', va='top',
            color=color_map.get(classification, 'black'),
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                      edgecolor=color_map.get(classification, 'black'),
                      alpha=0.9))
    
    ax.set_xlabel('CRISPR Incubation (min)', fontsize=11)
    ax.set_ylabel('Fluorescence (AU)', fontsize=11)
    ax.set_title('Fluorescence Detection', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Figure saved to {save_path}")
    
    plt.show()
    
    return classification


# ═══════════════════════════════════════════════════════════════════════
# MAIN — Run complete positive and negative assay demonstrations
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    os.makedirs('biology/results', exist_ok=True)
    
    print("=" * 65)
    print("  HYBRID-LAB  —  Multi-Domain Digital Twin")
    print("  End-to-End Assay Simulation")
    print("=" * 65)
    
    # ── Positive Test ────────────────────────────────────────────────
    print("\n▶ Running POSITIVE test...")
    config_pos = AssayConfiguration(
        name="Positive Control",
        target_present=True,
        target_concentration=1.0,
    )
    result_pos = run_assay(config_pos, add_noise=True, rng_seed=42)
    cls_pos = plot_assay_results(
        result_pos,
        save_path='biology/results/assay_positive.png'
    )
    print(f"  Result: {cls_pos}")
    print(f"  LAMP final A = {result_pos['transfer']['A_final_lamp']:.4f}")
    print(f"  Transferred  = {result_pos['transfer']['A_transferred']:.4f}")
    
    # ── Negative Test ────────────────────────────────────────────────
    print("\n▶ Running NEGATIVE test...")
    config_neg = AssayConfiguration(
        name="Negative Control",
        target_present=False,
        target_concentration=0.0,
    )
    result_neg = run_assay(config_neg, add_noise=True, rng_seed=43)
    cls_neg = plot_assay_results(
        result_neg,
        save_path='biology/results/assay_negative.png'
    )
    print(f"  Result: {cls_neg}")
    
    # ── Low Concentration (near LoD) ─────────────────────────────────
    print("\n▶ Running LOW CONCENTRATION test (near limit of detection)...")
    config_low = AssayConfiguration(
        name="Low Concentration (0.01×)",
        target_present=True,
        target_concentration=0.01,
    )
    result_low = run_assay(config_low, add_noise=True, rng_seed=44)
    cls_low = plot_assay_results(
        result_low,
        save_path='biology/results/assay_low_concentration.png'
    )
    print(f"  Result: {cls_low}")
    print(f"  LAMP final A = {result_low['transfer']['A_final_lamp']:.4f}")
    
    # ── Summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  SUMMARY")
    print("=" * 65)
    print(f"  Positive control:    {cls_pos}")
    print(f"  Negative control:    {cls_neg}")
    print(f"  Low concentration:   {cls_low}")
    print("=" * 65)
    print("\nPhase 1 (Biological Domain) simulation complete.")
    print("Output figures saved to biology/results/")
