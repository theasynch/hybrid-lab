"""
LAMP Amplification Kinetic Model
=================================

Reduced-order model for Loop-Mediated Isothermal Amplification.

This is NOT a molecular-dynamics simulation. It is a phenomenological
kinetic model that maps:

    target_present  →  amplified product concentration A(t)

The model uses a logistic growth form with temperature-dependent rate:

    dA/dt = k_a · η(T) · A · (1 - A/A_max)

where:
    A       = amplified product concentration (normalised, 0–1 scale)
    k_a     = effective amplification rate constant (1/min)
    η(T)    = temperature-dependent enzyme efficiency (0–1)
    A_max   = saturation capacity (normalised to 1.0)

Temperature dependence is modelled as a Gaussian activity window
centred on the optimal enzyme temperature (~63–65 °C for Bst polymerase):

    η(T) = exp(-(T - T_opt)² / (2·σ_T²))

References:
    - Notomi et al., Nucleic Acids Res. 28(12), e63, 2000
    - Nagamine et al., Mol. Cell. Probes 16(3), 223–229, 2002
    - Theoretical Paper Eq. (1): T + P + E + N → A (isothermal)

Note: All rate constants are illustrative. They must be calibrated
against experimental or literature-reported amplification curves
before any quantitative claim is made.
"""

import numpy as np
from scipy.integrate import solve_ivp
from dataclasses import dataclass, field
from typing import Optional, Callable


@dataclass
class LAMPParameters:
    """Parameters for the LAMP amplification model.
    
    Attributes:
        k_a: Effective amplification rate constant (1/min).
             Literature-derived LAMP reactions typically reach detectable
             amplification within 15–30 min; k_a is tuned accordingly.
        A_max: Saturation capacity (normalised). Represents the plateau
               of the sigmoidal amplification curve.
        T_opt: Optimal reaction temperature (°C). Bst 2.0 WarmStart
               polymerase operates optimally near 63–65 °C.
        sigma_T: Temperature sensitivity width (°C). Controls how
                 sharply enzyme efficiency drops away from T_opt.
        A_0_positive: Initial seed for target-present case. Represents
                      the effective starting template concentration.
        A_0_negative: Initial seed for target-absent case. Should be
                      essentially zero (or a tiny noise floor).
        lag_time: Lag phase duration (min) before exponential growth
                  begins. Models the initial primer-annealing and
                  strand-displacement phase.
    """
    k_a: float = 0.35          # 1/min — tuned for ~20 min time-to-positive
    A_max: float = 1.0         # normalised saturation
    T_opt: float = 63.0        # °C — Bst polymerase optimal
    sigma_T: float = 3.0       # °C — activity window width
    A_0_positive: float = 1e-4 # initial seed (target present)
    A_0_negative: float = 1e-9 # initial seed (target absent / noise floor)
    lag_time: float = 5.0      # min — initial lag before exponential phase


def enzyme_efficiency(T: float, T_opt: float = 63.0, sigma_T: float = 3.0) -> float:
    """Temperature-dependent enzyme activity.
    
    Models the Gaussian activity window of a strand-displacing polymerase.
    Outside the optimal range, amplification efficiency drops rapidly.
    
    Args:
        T: Current reaction temperature (°C).
        T_opt: Optimal temperature (°C).
        sigma_T: Width of the activity window (°C).
    
    Returns:
        Efficiency factor between 0 and 1.
    """
    return np.exp(-((T - T_opt) ** 2) / (2 * sigma_T ** 2))


def lamp_ode(t: float, y: np.ndarray, params: LAMPParameters,
             T_func: Optional[Callable] = None) -> list:
    """ODE right-hand side for LAMP amplification.
    
    Args:
        t: Time (min).
        y: State vector [A].
        params: LAMP model parameters.
        T_func: Callable returning temperature at time t.
                If None, assumes constant T_opt.
    
    Returns:
        [dA/dt]
    """
    A = y[0]
    
    # Get current temperature
    T = T_func(t) if T_func is not None else params.T_opt
    
    # Temperature-dependent efficiency
    eta = enzyme_efficiency(T, params.T_opt, params.sigma_T)
    
    # Lag-phase modulation: smooth ramp from 0 to 1
    # Uses a sigmoid to model the transition from lag to exponential phase
    lag_factor = 1.0 / (1.0 + np.exp(-2.0 * (t - params.lag_time)))
    
    # Logistic growth with temperature dependence
    dA_dt = params.k_a * eta * lag_factor * A * (1.0 - A / params.A_max)
    
    return [dA_dt]


def simulate_lamp(params: Optional[LAMPParameters] = None,
                  target_present: bool = True,
                  T_func: Optional[Callable] = None,
                  t_span: tuple = (0.0, 40.0),
                  t_eval: Optional[np.ndarray] = None,
                  ) -> dict:
    """Run LAMP amplification simulation.
    
    Args:
        params: Model parameters. Uses defaults if None.
        target_present: If True, uses A_0_positive; else A_0_negative.
        T_func: Temperature as a function of time (min → °C).
        t_span: (t_start, t_end) in minutes.
        t_eval: Time points to evaluate. If None, 500 evenly spaced points.
    
    Returns:
        Dictionary with keys:
            't': time array (min)
            'A': amplification product array
            'eta': enzyme efficiency array
            'success': solver success flag
    """
    if params is None:
        params = LAMPParameters()
    
    A_0 = params.A_0_positive if target_present else params.A_0_negative
    
    if t_eval is None:
        t_eval = np.linspace(t_span[0], t_span[1], 500)
    
    sol = solve_ivp(
        lamp_ode,
        t_span,
        [A_0],
        args=(params, T_func),
        t_eval=t_eval,
        method='RK45',
        rtol=1e-8,
        atol=1e-12,
        dense_output=True
    )
    
    # Compute efficiency at each time point
    if T_func is not None:
        eta = np.array([enzyme_efficiency(t, params.T_opt, params.sigma_T)
                        for t in sol.t])
    else:
        eta = np.ones_like(sol.t)
    
    return {
        't': sol.t,
        'A': sol.y[0],
        'eta': eta,
        'success': sol.success,
        'params': params,
    }


# ---------------------------------------------------------------------------
# Standalone demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    
    params = LAMPParameters()
    
    # --- Positive vs Negative ---
    pos = simulate_lamp(params, target_present=True)
    neg = simulate_lamp(params, target_present=False)
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    # Amplification curves
    ax = axes[0]
    ax.plot(pos['t'], pos['A'], linewidth=2, color='#2ecc71', label='Target PRESENT')
    ax.plot(neg['t'], neg['A'], linewidth=2, color='#e74c3c', label='Target ABSENT')
    ax.set_xlabel('Time (min)', fontsize=12)
    ax.set_ylabel('Amplified Product A(t)', fontsize=12)
    ax.set_title('LAMP Amplification Kinetics', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(-0.05, 1.15)
    
    # Temperature sensitivity
    ax = axes[1]
    temps = np.linspace(50, 80, 200)
    eta_vals = [enzyme_efficiency(T, params.T_opt, params.sigma_T) for T in temps]
    ax.plot(temps, eta_vals, linewidth=2, color='#3498db')
    ax.axvline(params.T_opt, color='#e74c3c', linestyle='--', alpha=0.7,
               label=f'T_opt = {params.T_opt}°C')
    ax.fill_between(temps, eta_vals, alpha=0.15, color='#3498db')
    ax.set_xlabel('Temperature (°C)', fontsize=12)
    ax.set_ylabel('Enzyme Efficiency η(T)', fontsize=12)
    ax.set_title('Temperature-Dependent Activity', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('biology/results/lamp_kinetics.png', dpi=150, bbox_inches='tight')
    plt.show()
    print("LAMP model simulation complete.")
