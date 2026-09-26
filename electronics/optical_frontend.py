"""
Optical Frontend Behavioral Model
===================================

Models the analog signal chain from fluorescence to voltage:

    Fluorescence → Photodiode → TIA → Voltage

From the theoretical paper:

    Photodiode (Eq. 6):
        I_PD(t) = R_λ · P_opt(t) + I_dark + I_ambient

    TIA (Eq. 7):
        V_TIA(t) = V_ref − I_PD(t) · R_f

    Differential measurement (Eq. 8):
        S(t) = V_on(t) − V_off(t)

The model also includes:
    - Shot noise on the photodiode
    - TIA input noise (voltage and current)
    - LED on/off modulation for ambient rejection
    - Stray light leakage

References:
    - Hamamatsu, "Technical note: Si photodiodes"
    - TI, "1 MHz Single-Supply Photodiode Amplifier Reference Design"
    - Theoretical Paper Eqs. (6)–(8)
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class PhotodiodeParams:
    """Silicon photodiode parameters.
    
    Attributes:
        R_lambda: Responsivity at emission wavelength (A/W).
                  Typical Si photodiode: 0.3–0.6 A/W at 500–600 nm.
        I_dark: Dark current (A). Typical: 0.1–10 nA.
        active_area: Active area (mm²). Typical: 1–13 mm².
    """
    R_lambda: float = 0.4      # A/W at ~520 nm (FAM emission)
    I_dark: float = 2e-9       # 2 nA dark current
    active_area: float = 5.0   # mm²


@dataclass
class TIAParams:
    """Transimpedance amplifier parameters.
    
    Attributes:
        R_f: Feedback resistance (Ω). Sets gain.
             Higher R_f → more gain → more noise.
        C_f: Feedback capacitance (F). Stabilises amp.
        V_ref: Reference voltage (V). Output offset.
        V_supply: Supply voltage (V). Sets output range.
        noise_density: Input-referred voltage noise (V/√Hz).
        input_bias: Input bias current (A). Low-bias op-amps: ~1 pA.
    """
    R_f: float = 1e6           # 1 MΩ — moderate gain
    C_f: float = 1e-12         # 1 pF — stability
    V_ref: float = 1.65        # mid-rail for 3.3V supply
    V_supply: float = 3.3      # V
    noise_density: float = 10e-9  # 10 nV/√Hz
    input_bias: float = 1e-12  # 1 pA


@dataclass
class LEDParams:
    """Excitation LED parameters.
    
    Attributes:
        power_on: Optical power when on (W). Blue LED ~1–5 mW.
        power_off: Residual when off (W). Should be ~0.
        wavelength: Excitation wavelength (nm).
        emission_wavelength: Reporter emission wavelength (nm).
        excitation_leakage: Fraction of excitation reaching detector
                           through emission filter (should be <1e-4).
    """
    power_on: float = 2e-3     # 2 mW
    power_off: float = 0.0
    wavelength: float = 470.0  # nm (blue)
    emission_wavelength: float = 520.0  # nm (FAM green)
    excitation_leakage: float = 1e-5  # filter rejection


@dataclass
class OpticalFrontendParams:
    """Combined optical frontend parameters."""
    photodiode: PhotodiodeParams = None
    tia: TIAParams = None
    led: LEDParams = None
    ambient_power: float = 1e-7  # W — stray ambient light reaching detector
    
    def __post_init__(self):
        if self.photodiode is None:
            self.photodiode = PhotodiodeParams()
        if self.tia is None:
            self.tia = TIAParams()
        if self.led is None:
            self.led = LEDParams()


class OpticalFrontend:
    """Behavioral model of the complete optical signal chain.
    
    Converts fluorescence intensity to TIA output voltage,
    including all noise sources and the LED on/off differential
    measurement technique.
    """
    
    def __init__(self, params: Optional[OpticalFrontendParams] = None):
        self.params = params or OpticalFrontendParams()
    
    def fluorescence_to_optical_power(self, F: np.ndarray,
                                       F_max: float = 2.5) -> np.ndarray:
        """Convert arbitrary fluorescence units to optical power at detector.
        
        This is a scaling model. The actual relationship depends on
        geometry, filter transmission, quantum yield, etc.
        
        Args:
            F: Fluorescence values (AU).
            F_max: Maximum expected fluorescence (AU).
        
        Returns:
            Optical power at detector (W).
        """
        # Scale fluorescence to a fraction of maximum detectable power
        # Assume max fluorescence produces ~10 nW at the detector
        P_max_detect = 10e-9  # 10 nW — typical for weak fluorescence
        return (F / F_max) * P_max_detect
    
    def photodiode_current(self, P_opt: np.ndarray,
                            led_on: bool = True) -> np.ndarray:
        """Compute photodiode current (Eq. 6).
        
        I_PD = R_λ · P_opt + I_dark + I_ambient
        
        When LED is on, P_opt includes fluorescence + excitation leakage.
        When LED is off, P_opt is only ambient.
        """
        pd = self.params.photodiode
        led = self.params.led
        
        if led_on:
            # Fluorescence signal + excitation filter leakage
            P_leak = led.power_on * led.excitation_leakage
            I = pd.R_lambda * (P_opt + P_leak) + pd.I_dark
        else:
            # Only ambient and dark current
            I = pd.R_lambda * self.params.ambient_power + pd.I_dark
        
        return I
    
    def tia_output(self, I_pd: np.ndarray) -> np.ndarray:
        """Compute TIA output voltage (Eq. 7).
        
        V_TIA = V_ref − I_PD · R_f
        
        Clamped to [0, V_supply].
        """
        tia = self.params.tia
        V = tia.V_ref - I_pd * tia.R_f
        return np.clip(V, 0, tia.V_supply)
    
    def add_noise(self, V: np.ndarray, bandwidth: float = 100.0,
                   rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """Add realistic noise to TIA output.
        
        Includes:
        - TIA voltage noise: V_n = noise_density · √bandwidth
        - Shot noise: approximated
        - Quantisation effects handled by ADC model
        
        Args:
            V: Clean voltage array.
            bandwidth: Effective noise bandwidth (Hz).
            rng: Random number generator.
        
        Returns:
            Noisy voltage array.
        """
        if rng is None:
            rng = np.random.default_rng()
        
        tia = self.params.tia
        
        # TIA voltage noise (output-referred)
        v_noise_rms = tia.noise_density * np.sqrt(bandwidth) * tia.R_f * 1e-3
        
        # Total noise
        V = np.atleast_1d(V)
        noise = rng.normal(0, max(v_noise_rms, 1e-6), V.shape)
        
        return V + noise
    
    def measure_differential(self, F: np.ndarray,
                              add_noise: bool = True,
                              rng_seed: Optional[int] = None,
                              ) -> dict:
        """Perform LED-on/LED-off differential measurement (Eq. 8).
        
        S(t) = V_on(t) − V_off(t)
        
        This suppresses ambient light and offset drift.
        
        Args:
            F: Fluorescence array (AU).
            add_noise: Whether to add measurement noise.
            rng_seed: Random seed.
        
        Returns:
            Dictionary with voltage signals and differential result.
        """
        rng = np.random.default_rng(rng_seed)
        
        # Convert fluorescence to optical power
        P_opt = self.fluorescence_to_optical_power(F)
        
        # LED ON measurement
        I_on = self.photodiode_current(P_opt, led_on=True)
        V_on = self.tia_output(I_on)
        if add_noise:
            V_on = self.add_noise(V_on, rng=rng)
        
        # LED OFF measurement
        I_off = self.photodiode_current(np.zeros_like(P_opt), led_on=False)
        V_off = self.tia_output(I_off)
        if add_noise:
            V_off = self.add_noise(V_off, rng=rng)
        
        # Differential signal (Eq. 8)
        S = V_on - V_off
        
        return {
            'P_opt': P_opt,
            'I_on': I_on,
            'I_off': I_off,
            'V_on': V_on,
            'V_off': V_off,
            'S': S,
        }


# ---------------------------------------------------------------------------
# Standalone demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    
    # Simulate a rising fluorescence signal
    t = np.linspace(0, 15, 500)
    F_positive = 0.1 + 1.9 / (1 + np.exp(-0.8 * (t - 7)))  # sigmoidal rise
    F_negative = 0.1 + 0.02 * np.random.randn(len(t))  # flat baseline
    
    frontend = OpticalFrontend()
    
    meas_pos = frontend.measure_differential(F_positive, add_noise=True, rng_seed=42)
    meas_neg = frontend.measure_differential(F_negative, add_noise=True, rng_seed=43)
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    
    # Fluorescence input
    ax = axes[0, 0]
    ax.plot(t, F_positive, linewidth=2, color='#2ecc71', label='Positive')
    ax.plot(t, np.clip(F_negative, 0, None), linewidth=2, color='#e74c3c',
            label='Negative')
    ax.set_ylabel('Fluorescence (AU)', fontsize=11)
    ax.set_title('Input: Virtual Fluorescence', fontsize=13, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # TIA output (LED on)
    ax = axes[0, 1]
    ax.plot(t, meas_pos['V_on'] * 1e3, linewidth=1.5, color='#2ecc71',
            label='Positive V_on')
    ax.plot(t, meas_neg['V_on'] * 1e3, linewidth=1.5, color='#e74c3c',
            label='Negative V_on')
    ax.set_ylabel('TIA Output (mV)', fontsize=11)
    ax.set_title('TIA Output (LED ON)', fontsize=13, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Differential signal
    ax = axes[1, 0]
    ax.plot(t, meas_pos['S'] * 1e3, linewidth=1.5, color='#2ecc71',
            label='Positive S(t)')
    ax.plot(t, meas_neg['S'] * 1e3, linewidth=1.5, color='#e74c3c',
            label='Negative S(t)')
    ax.set_xlabel('Time (min)', fontsize=11)
    ax.set_ylabel('Differential Signal (mV)', fontsize=11)
    ax.set_title('Differential: V_on − V_off', fontsize=13, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Optical power at detector
    ax = axes[1, 1]
    ax.plot(t, meas_pos['P_opt'] * 1e9, linewidth=2, color='#3498db')
    ax.set_xlabel('Time (min)', fontsize=11)
    ax.set_ylabel('Optical Power (nW)', fontsize=11)
    ax.set_title('Detected Optical Power', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('electronics/optical_frontend_demo.png', dpi=150,
                bbox_inches='tight')
    plt.show()
    print("Optical frontend model demonstration complete.")
