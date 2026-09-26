"""
CRISPR-Cas12a Activation and Reporter Cleavage Model
=====================================================

Reduced-order kinetic model for the CRISPR detection stage.

The two-stage reaction:

    Stage 1 — Cas12a activation:
        Cas12a_inactive + Amplicon → Cas12a_active
        dC_active/dt = k_c · A(t) · C_inactive

    Stage 2 — Collateral reporter cleavage:
        Reporter + Cas12a_active → Fluorophore + Quencher (separated)
        dR/dt = -k_r · C_active · R

This models the trans-cleavage property of Cas12a: once activated
by target recognition, Cas12a indiscriminately cleaves nearby
single-stranded DNA reporters (FQ reporters).

References:
    - Chen et al., Science 360(6387), 436–439, 2018  (DETECTR)
    - Broughton et al., Nature Biotechnology 38, 870–874, 2020
    - Theoretical Paper Eq. (3): FQ reporter → F + Q (via activated Cas12a)

Note: Rate constants are phenomenological and must be calibrated
against experimental reporter-cleavage kinetics.
"""

import numpy as np
from scipy.integrate import solve_ivp
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class CRISPRParameters:
    """Parameters for the Cas12a detection model.
    
    Attributes:
        k_c: Cas12a activation rate constant (1/(conc·min)).
             Controls how quickly Cas12a is activated by amplicon.
        k_r: Reporter cleavage rate constant (1/(conc·min)).
             Controls the trans-cleavage speed once Cas12a is active.
        C_total: Total Cas12a concentration (normalised).
        R_0: Initial intact reporter concentration (normalised).
        C_active_0: Initial activated Cas12a (should be ~0).
        incubation_temp: Cas12a incubation temperature (°C).
             Cas12a typically operates at 37 °C, though some variants
             work at ambient temperature.
        T_opt_cas: Optimal temperature for Cas12a (°C).
        sigma_T_cas: Temperature sensitivity width (°C).
    """
    k_c: float = 0.8           # activation rate
    k_r: float = 1.2           # reporter cleavage rate (trans-cleavage is fast)
    C_total: float = 1.0       # total Cas12a (normalised)
    R_0: float = 1.0           # initial reporter (normalised)
    C_active_0: float = 0.0    # initially no activated Cas12a
    incubation_temp: float = 37.0  # °C
    T_opt_cas: float = 37.0    # °C — Cas12a optimum
    sigma_T_cas: float = 5.0   # °C — broader activity window than polymerase


def cas12a_activity(T: float, T_opt: float = 37.0, sigma_T: float = 5.0) -> float:
    """Temperature-dependent Cas12a activity.
    
    Args:
        T: Current temperature (°C).
        T_opt: Optimal temperature (°C).
        sigma_T: Activity window width (°C).
    
    Returns:
        Activity factor between 0 and 1.
    """
    return np.exp(-((T - T_opt) ** 2) / (2 * sigma_T ** 2))


def crispr_ode(t: float, y: np.ndarray, params: CRISPRParameters,
               A_func: Optional[Callable] = None,
               T_func: Optional[Callable] = None) -> list:
    """ODE right-hand side for Cas12a activation + reporter cleavage.
    
    State vector y = [C_active, R]
    
    Args:
        t: Time (min) — relative to start of CRISPR incubation.
        y: State vector [C_active, R].
        params: CRISPR model parameters.
        A_func: Callable returning amplicon concentration at time t.
                This represents the amount of LAMP product transferred.
                If None, assumes saturated amplicon (A=1.0).
        T_func: Callable returning temperature at time t.
                If None, assumes constant incubation_temp.
    
    Returns:
        [dC_active/dt, dR/dt]
    """
    C_active = max(y[0], 0.0)
    R = max(y[1], 0.0)
    
    # Amplicon available for Cas12a recognition
    A = A_func(t) if A_func is not None else 1.0
    
    # Temperature-dependent activity
    T = T_func(t) if T_func is not None else params.incubation_temp
    eta_cas = cas12a_activity(T, params.T_opt_cas, params.sigma_T_cas)
    
    # Inactive Cas12a remaining
    C_inactive = max(params.C_total - C_active, 0.0)
    
    # Activation: Cas12a_inactive + Amplicon → Cas12a_active
    dC_active_dt = params.k_c * eta_cas * A * C_inactive
    
    # Reporter cleavage: Reporter → F + Q (collateral/trans cleavage)
    dR_dt = -params.k_r * eta_cas * C_active * R
    
    return [dC_active_dt, dR_dt]


def simulate_crispr(params: Optional[CRISPRParameters] = None,
                    A_func: Optional[Callable] = None,
                    T_func: Optional[Callable] = None,
                    t_span: tuple = (0.0, 20.0),
                    t_eval: Optional[np.ndarray] = None,
                    ) -> dict:
    """Run CRISPR-Cas12a detection simulation.
    
    Args:
        params: Model parameters. Uses defaults if None.
        A_func: Amplicon concentration as a function of time.
                For a positive test, this might be a constant ~1.0
                (saturated LAMP product transferred).
                For a negative test, ~0.0.
        T_func: Temperature as a function of time.
        t_span: (t_start, t_end) in minutes.
        t_eval: Time points to evaluate.
    
    Returns:
        Dictionary with keys:
            't': time array (min)
            'C_active': activated Cas12a array
            'R': intact reporter array
            'R_cleaved': cleaved reporter (R_0 - R)
            'success': solver success flag
    """
    if params is None:
        params = CRISPRParameters()
    
    if t_eval is None:
        t_eval = np.linspace(t_span[0], t_span[1], 500)
    
    y0 = [params.C_active_0, params.R_0]
    
    sol = solve_ivp(
        crispr_ode,
        t_span,
        y0,
        args=(params, A_func, T_func),
        t_eval=t_eval,
        method='RK45',
        rtol=1e-8,
        atol=1e-12,
    )
    
    return {
        't': sol.t,
        'C_active': sol.y[0],
        'R': sol.y[1],
        'R_cleaved': params.R_0 - sol.y[1],
        'success': sol.success,
        'params': params,
    }


# ---------------------------------------------------------------------------
# Standalone demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    
    params = CRISPRParameters()
    
    # Positive case: saturated amplicon transferred
    pos = simulate_crispr(params, A_func=lambda t: 1.0)
    
    # Negative case: no amplicon
    neg = simulate_crispr(params, A_func=lambda t: 0.0)
    
    # Weak positive: partial amplification
    weak = simulate_crispr(params, A_func=lambda t: 0.1)
    
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    
    # Cas12a activation
    ax = axes[0]
    ax.plot(pos['t'], pos['C_active'], linewidth=2, color='#2ecc71',
            label='Strong positive (A=1.0)')
    ax.plot(weak['t'], weak['C_active'], linewidth=2, color='#f39c12',
            label='Weak positive (A=0.1)')
    ax.plot(neg['t'], neg['C_active'], linewidth=2, color='#e74c3c',
            label='Negative (A=0.0)')
    ax.set_xlabel('Incubation Time (min)', fontsize=12)
    ax.set_ylabel('Activated Cas12a', fontsize=12)
    ax.set_title('Cas12a Activation', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    # Reporter cleavage
    ax = axes[1]
    ax.plot(pos['t'], pos['R'], linewidth=2, color='#2ecc71', label='Positive')
    ax.plot(weak['t'], weak['R'], linewidth=2, color='#f39c12', label='Weak')
    ax.plot(neg['t'], neg['R'], linewidth=2, color='#e74c3c', label='Negative')
    ax.set_xlabel('Incubation Time (min)', fontsize=12)
    ax.set_ylabel('Intact Reporter R(t)', fontsize=12)
    ax.set_title('Reporter Cleavage', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    # Cleaved reporter (proportional to fluorescence)
    ax = axes[2]
    ax.plot(pos['t'], pos['R_cleaved'], linewidth=2, color='#2ecc71',
            label='Positive')
    ax.plot(weak['t'], weak['R_cleaved'], linewidth=2, color='#f39c12',
            label='Weak positive')
    ax.plot(neg['t'], neg['R_cleaved'], linewidth=2, color='#e74c3c',
            label='Negative')
    ax.set_xlabel('Incubation Time (min)', fontsize=12)
    ax.set_ylabel('Cleaved Reporter (R₀ − R)', fontsize=12)
    ax.set_title('Cleaved Reporter → Fluorescence', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('biology/results/crispr_kinetics.png', dpi=150, bbox_inches='tight')
    plt.show()
    print("CRISPR-Cas12a model simulation complete.")
