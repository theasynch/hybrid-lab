"""
Virtual Fluorescence Signal Generator
======================================

Converts cleaved reporter concentration into a fluorescence signal
that mimics what a real photodiode would observe.

The core relation (from the theoretical paper):

    F(t) = F_0 + α · (R_0 − R(t))

where:
    F_0    = baseline fluorescence (background + autofluorescence)
    α      = proportionality constant (fluorescence per unit cleaved reporter)
    R_0    = initial intact reporter concentration
    R(t)   = remaining intact reporter at time t

This module also adds realistic artefacts:
    - Baseline drift (slow linear or polynomial drift)
    - Photobleaching (exponential decay of fluorescence over time)
    - Random measurement noise
    - LED intensity variation

References:
    - Theoretical Paper: F(t) = F_0 + α(R_0 − R(t))
    - Simulation Plan Section 10: virtual fluorescence curve
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class FluorescenceParameters:
    """Parameters for fluorescence signal generation.
    
    Attributes:
        F_0: Baseline fluorescence (arbitrary units).
             Represents background autofluorescence + dark signal.
        alpha: Fluorescence proportionality constant.
               Scales cleaved reporter to fluorescence units.
        noise_std: Standard deviation of measurement noise (AU).
        drift_rate: Linear baseline drift (AU/min).
                    Positive = upward drift (thermal, electronic).
        photobleach_tau: Photobleaching time constant (min).
                        Set to inf for no photobleaching.
        led_variation_std: LED intensity variation (fractional, 0–1).
    """
    F_0: float = 0.10           # baseline fluorescence (AU)
    alpha: float = 2.0          # fluorescence per unit cleaved reporter
    noise_std: float = 0.02     # measurement noise
    drift_rate: float = 0.001   # AU/min — slow baseline drift
    photobleach_tau: float = 200.0  # min — slow photobleaching
    led_variation_std: float = 0.005  # 0.5% LED variation


def generate_fluorescence(t: np.ndarray,
                          R: np.ndarray,
                          R_0: float = 1.0,
                          params: Optional[FluorescenceParameters] = None,
                          add_noise: bool = True,
                          rng_seed: Optional[int] = None,
                          ) -> dict:
    """Generate virtual fluorescence signal from reporter cleavage data.
    
    Args:
        t: Time array (min).
        R: Intact reporter concentration array (same length as t).
        R_0: Initial reporter concentration.
        params: Fluorescence model parameters.
        add_noise: Whether to add measurement noise and artefacts.
        rng_seed: Random seed for reproducibility.
    
    Returns:
        Dictionary with keys:
            'F_ideal': Clean fluorescence signal
            'F_noisy': Fluorescence with all noise/artefacts
            'F_baseline': Baseline component
            'F_drift': Drift component
            'noise': Added noise
    """
    if params is None:
        params = FluorescenceParameters()
    
    rng = np.random.default_rng(rng_seed)
    
    # --- Ideal fluorescence ---
    # F(t) = F_0 + α · (R_0 − R(t))
    R_cleaved = R_0 - R
    F_ideal = params.F_0 + params.alpha * R_cleaved
    
    if not add_noise:
        return {
            'F_ideal': F_ideal,
            'F_noisy': F_ideal.copy(),
            'F_baseline': np.full_like(t, params.F_0),
            'F_drift': np.zeros_like(t),
            'noise': np.zeros_like(t),
        }
    
    # --- Baseline drift ---
    drift = params.drift_rate * t
    
    # --- Photobleaching ---
    bleach = np.exp(-t / params.photobleach_tau)
    
    # --- LED intensity variation ---
    led_var = 1.0 + rng.normal(0, params.led_variation_std, len(t))
    
    # --- Measurement noise ---
    noise = rng.normal(0, params.noise_std, len(t))
    
    # --- Composite signal ---
    F_noisy = (F_ideal * bleach * led_var) + drift + noise
    
    return {
        'F_ideal': F_ideal,
        'F_noisy': F_noisy,
        'F_baseline': np.full_like(t, params.F_0),
        'F_drift': drift,
        'noise': noise,
        'bleach_factor': bleach,
    }


def compute_normalized_fluorescence(S: np.ndarray,
                                     S_baseline: float,
                                     S_reference: float,
                                     epsilon: float = 1e-6) -> np.ndarray:
    """Compute normalised fluorescence metric (Eq. 9 from the paper).
    
    F_N(t) = (S(t) − S_baseline) / max(ε, S_reference)
    
    Args:
        S: Differential signal array (V_on − V_off).
        S_baseline: Baseline signal (from early samples).
        S_reference: Reference signal for normalisation.
        epsilon: Small value to prevent division by zero.
    
    Returns:
        Normalised fluorescence array.
    """
    return (S - S_baseline) / max(epsilon, S_reference)


# ---------------------------------------------------------------------------
# Standalone demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    from lamp_model import simulate_lamp
    from crispr_model import simulate_crispr
    
    # Simulate full positive assay
    lamp_result = simulate_lamp(target_present=True, t_span=(0, 30))
    A_final = lamp_result['A'][-1]  # amplicon transferred to CRISPR
    
    crispr_result = simulate_crispr(A_func=lambda t: A_final, t_span=(0, 15))
    
    # Generate fluorescence
    params = FluorescenceParameters()
    fluo = generate_fluorescence(
        crispr_result['t'],
        crispr_result['R'],
        R_0=1.0,
        params=params,
        add_noise=True,
        rng_seed=42,
    )
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    ax = axes[0]
    ax.plot(crispr_result['t'], fluo['F_ideal'], linewidth=2,
            color='#2ecc71', label='Ideal F(t)')
    ax.plot(crispr_result['t'], fluo['F_noisy'], linewidth=1,
            color='#3498db', alpha=0.7, label='Noisy F(t)')
    ax.set_xlabel('CRISPR Incubation Time (min)', fontsize=12)
    ax.set_ylabel('Fluorescence (AU)', fontsize=12)
    ax.set_title('Virtual Fluorescence Signal', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    
    # Negative test
    crispr_neg = simulate_crispr(A_func=lambda t: 0.0, t_span=(0, 15))
    fluo_neg = generate_fluorescence(
        crispr_neg['t'], crispr_neg['R'], R_0=1.0,
        params=params, add_noise=True, rng_seed=43,
    )
    
    ax = axes[1]
    ax.plot(crispr_result['t'], fluo['F_noisy'], linewidth=1.5,
            color='#2ecc71', label='POSITIVE')
    ax.plot(crispr_neg['t'], fluo_neg['F_noisy'], linewidth=1.5,
            color='#e74c3c', label='NEGATIVE')
    ax.axhline(y=0.5, color='#f39c12', linestyle='--', linewidth=2,
               label='Threshold', alpha=0.8)
    ax.set_xlabel('CRISPR Incubation Time (min)', fontsize=12)
    ax.set_ylabel('Fluorescence (AU)', fontsize=12)
    ax.set_title('Positive vs Negative', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('biology/results/fluorescence_signal.png', dpi=150,
                bbox_inches='tight')
    plt.show()
    print("Fluorescence model demonstration complete.")
