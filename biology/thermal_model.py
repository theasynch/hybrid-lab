"""
Lumped Thermal Model and PID Controller
========================================

Models the thermal behaviour of the reaction chamber using a
first-order RC equivalent circuit (Eq. 4 from the theoretical paper):

    C_th · dT/dt = P_h(t) − (T(t) − T_a(t)) / R_th

where:
    C_th  = effective thermal capacitance (J/K)
    R_th  = thermal resistance to ambient (K/W)
    P_h   = applied heater power (W)
    T_a   = ambient temperature (°C)
    T     = chamber temperature (°C)

PID controller (Eq. 5 from the paper):

    u(t) = K_p·e(t) + K_i·∫e(τ)dτ + K_d·de/dt

with anti-windup and output clamping (0–100% PWM).

The thermal model is used to:
    1. Size the heater for required warm-up time
    2. Design the PID controller
    3. Generate realistic temperature profiles for the LAMP/CRISPR models
    4. Simulate temperature faults (under/overshoot, sensor failure)

References:
    - Bergman et al., Fundamentals of Heat and Mass Transfer, 8th ed.
    - Åström & Hägglund, Advanced PID Control, ISA, 2006
    - Theoretical Paper Eqs. (4)–(5)
"""

import numpy as np
from scipy.integrate import solve_ivp
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class ThermalParameters:
    """Physical parameters for the lumped thermal model.
    
    Default values are illustrative for a small aluminium thermal
    block (~20 g) with a polyimide heater.
    
    Attributes:
        C_th: Thermal capacitance (J/K).
              Aluminium ~900 J/(kg·K), 20g block → ~18 J/K.
        R_th: Thermal resistance to ambient (K/W).
              Depends on enclosure insulation. ~5 K/W is moderate.
        T_ambient: Ambient temperature (°C).
        P_max: Maximum heater power (W).
              A 5V, 2A polyimide heater → 10 W max.
    """
    C_th: float = 18.0         # J/K
    R_th: float = 5.0          # K/W
    T_ambient: float = 25.0    # °C
    P_max: float = 10.0        # W


@dataclass
class PIDParameters:
    """PID controller parameters.
    
    Attributes:
        K_p: Proportional gain.
        K_i: Integral gain (1/s).
        K_d: Derivative gain (s).
        output_min: Minimum output (0 = heater off).
        output_max: Maximum output (1 = full power).
        windup_limit: Anti-windup integral limit.
        d_filter_tau: Derivative filter time constant (s).
                      Prevents noise amplification.
    """
    K_p: float = 2.0
    K_i: float = 0.15
    K_d: float = 0.5
    output_min: float = 0.0
    output_max: float = 1.0
    windup_limit: float = 50.0
    d_filter_tau: float = 1.0  # seconds


class PIDController:
    """Discrete PID controller with anti-windup and derivative filtering.
    
    Designed for embedded implementation on microcontroller (ESP32-S3).
    """
    
    def __init__(self, params: Optional[PIDParameters] = None):
        self.params = params or PIDParameters()
        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_derivative = 0.0
        self.prev_time = None
    
    def reset(self):
        """Reset controller state."""
        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_derivative = 0.0
        self.prev_time = None
    
    def update(self, setpoint: float, measurement: float,
               current_time: float) -> float:
        """Compute PID output.
        
        Args:
            setpoint: Target temperature (°C).
            measurement: Current temperature (°C).
            current_time: Current time (seconds).
        
        Returns:
            Controller output (0.0–1.0, fractional heater power).
        """
        p = self.params
        
        # Time step
        if self.prev_time is None:
            dt = 0.1  # initial step
        else:
            dt = current_time - self.prev_time
            if dt <= 0:
                dt = 0.1
        
        # Error
        error = setpoint - measurement
        
        # Proportional
        P = p.K_p * error
        
        # Integral with anti-windup
        self.integral += error * dt
        self.integral = np.clip(self.integral, -p.windup_limit, p.windup_limit)
        I = p.K_i * self.integral
        
        # Filtered derivative (low-pass to reject noise)
        raw_derivative = (error - self.prev_error) / dt if dt > 0 else 0.0
        alpha = dt / (p.d_filter_tau + dt)
        filtered_derivative = alpha * raw_derivative + (1 - alpha) * self.prev_derivative
        D = p.K_d * filtered_derivative
        
        # Total output
        output = P + I + D
        output = np.clip(output, p.output_min, p.output_max)
        
        # Store state
        self.prev_error = error
        self.prev_derivative = filtered_derivative
        self.prev_time = current_time
        
        return output


def thermal_ode(t: float, y: np.ndarray, thermal_params: ThermalParameters,
                power_fraction: float) -> list:
    """ODE for the lumped thermal model.
    
    Args:
        t: Time (seconds).
        y: State vector [T].
        thermal_params: Physical parameters.
        power_fraction: Heater power as fraction of P_max (0–1).
    
    Returns:
        [dT/dt]
    """
    T = y[0]
    p = thermal_params
    
    P_h = power_fraction * p.P_max
    heat_loss = (T - p.T_ambient) / p.R_th
    
    dT_dt = (P_h - heat_loss) / p.C_th
    
    return [dT_dt]


def simulate_thermal_profile(setpoint_schedule: list,
                              thermal_params: Optional[ThermalParameters] = None,
                              pid_params: Optional[PIDParameters] = None,
                              dt: float = 0.1,
                              total_time: Optional[float] = None,
                              T_initial: Optional[float] = None,
                              ) -> dict:
    """Simulate the complete thermal profile with PID control.
    
    Args:
        setpoint_schedule: List of (time_seconds, setpoint_celsius) tuples.
                          e.g., [(0, 63), (1800, 37), (3000, 25)]
                          for LAMP → CRISPR → cool-down.
        thermal_params: Physical parameters.
        pid_params: PID controller parameters.
        dt: Simulation time step (seconds).
        total_time: Total simulation duration. If None, inferred from schedule.
        T_initial: Initial temperature. If None, uses T_ambient.
    
    Returns:
        Dictionary with keys:
            't': time array (seconds)
            't_min': time array (minutes)
            'T': temperature array (°C)
            'setpoint': setpoint array (°C)
            'power': heater power fraction array
            'error': temperature error array
    """
    if thermal_params is None:
        thermal_params = ThermalParameters()
    if pid_params is None:
        pid_params = PIDParameters()
    
    if total_time is None:
        total_time = max(t for t, _ in setpoint_schedule) + 300.0
    
    if T_initial is None:
        T_initial = thermal_params.T_ambient
    
    # Sort schedule
    schedule = sorted(setpoint_schedule, key=lambda x: x[0])
    
    def get_setpoint(t):
        """Piecewise-constant setpoint from schedule."""
        sp = schedule[0][1]
        for t_s, sp_s in schedule:
            if t >= t_s:
                sp = sp_s
        return sp
    
    # Run simulation
    pid = PIDController(pid_params)
    
    n_steps = int(total_time / dt) + 1
    t_arr = np.linspace(0, total_time, n_steps)
    T_arr = np.zeros(n_steps)
    sp_arr = np.zeros(n_steps)
    power_arr = np.zeros(n_steps)
    error_arr = np.zeros(n_steps)
    
    T_arr[0] = T_initial
    
    for i in range(1, n_steps):
        t_now = t_arr[i]
        T_now = T_arr[i - 1]
        sp = get_setpoint(t_now)
        sp_arr[i] = sp
        
        # PID output
        power_frac = pid.update(sp, T_now, t_now)
        power_arr[i] = power_frac
        error_arr[i] = sp - T_now
        
        # Integrate thermal ODE one step
        sol = solve_ivp(
            thermal_ode, [t_arr[i-1], t_now], [T_now],
            args=(thermal_params, power_frac),
            method='RK45',
        )
        T_arr[i] = sol.y[0][-1]
    
    sp_arr[0] = get_setpoint(0)
    
    return {
        't': t_arr,
        't_min': t_arr / 60.0,
        'T': T_arr,
        'setpoint': sp_arr,
        'power': power_arr,
        'error': error_arr,
    }


def create_lamp_crispr_schedule(lamp_temp: float = 63.0,
                                 lamp_duration_min: float = 30.0,
                                 crispr_temp: float = 37.0,
                                 crispr_duration_min: float = 15.0,
                                 cooldown_temp: float = 25.0,
                                 ) -> list:
    """Create a two-stage thermal schedule for LAMP → CRISPR.
    
    Returns:
        List of (time_seconds, setpoint_celsius) tuples.
    """
    lamp_end = lamp_duration_min * 60
    crispr_end = lamp_end + crispr_duration_min * 60
    
    return [
        (0, lamp_temp),            # Start LAMP heating
        (lamp_end, crispr_temp),   # Transition to CRISPR temp
        (crispr_end, cooldown_temp),  # Cool down
    ]


# ---------------------------------------------------------------------------
# Standalone demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    
    # Two-stage schedule: LAMP at 63°C → CRISPR at 37°C
    schedule = create_lamp_crispr_schedule()
    
    result = simulate_thermal_profile(
        setpoint_schedule=schedule,
        total_time=55 * 60,  # 55 minutes total
    )
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    
    # Temperature profile
    ax = axes[0]
    ax.plot(result['t_min'], result['T'], linewidth=2, color='#e74c3c',
            label='Chamber Temperature')
    ax.plot(result['t_min'], result['setpoint'], linewidth=2,
            color='#3498db', linestyle='--', label='Setpoint')
    ax.fill_between(result['t_min'],
                     result['setpoint'] - 0.5,
                     result['setpoint'] + 0.5,
                     alpha=0.15, color='#3498db', label='±0.5°C band')
    ax.set_ylabel('Temperature (°C)', fontsize=12)
    ax.set_title('Thermal Profile: LAMP → CRISPR', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    
    # Add phase annotations
    ax.axvspan(0, 30, alpha=0.05, color='green')
    ax.axvspan(30, 45, alpha=0.05, color='blue')
    ax.text(15, 20, 'LAMP (63°C)', ha='center', fontsize=11, style='italic')
    ax.text(37.5, 20, 'CRISPR (37°C)', ha='center', fontsize=11, style='italic')
    
    # Heater power
    ax = axes[1]
    ax.plot(result['t_min'], result['power'] * 100, linewidth=1.5,
            color='#f39c12')
    ax.fill_between(result['t_min'], result['power'] * 100, alpha=0.2,
                     color='#f39c12')
    ax.set_xlabel('Time (min)', fontsize=12)
    ax.set_ylabel('Heater Power (%)', fontsize=12)
    ax.set_title('PID Controller Output', fontsize=14, fontweight='bold')
    ax.set_ylim(-5, 110)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('biology/results/thermal_profile.png', dpi=150, bbox_inches='tight')
    plt.show()
    print("Thermal model simulation complete.")
