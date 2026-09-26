"""
ADC Behavioral Model
=====================

Models an analog-to-digital converter for the optical frontend.

Converts TIA voltage to digital counts with:
    - Quantisation (configurable resolution)
    - Sampling at defined rate
    - DNL/INL non-linearity (optional)
    - Quantisation noise
    - Input-referred noise

The default is a 12-bit ADC typical of an ESP32-S3 or external
SAR ADC (e.g., ADS1115).

References:
    - Theoretical Paper Table III: "MCU ADC for early tests;
      external precision ADC if required"
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class ADCParams:
    """ADC parameters.
    
    Attributes:
        resolution_bits: ADC resolution (bits).
        v_ref: Reference voltage (V). Full-scale input range.
        v_min: Minimum input voltage (V).
        v_max: Maximum input voltage (V). Usually = v_ref.
        sample_rate_hz: Sampling frequency (Hz).
        enob: Effective number of bits (accounts for noise).
              ENOB < resolution_bits due to noise and non-linearity.
        input_noise_lsb: Input-referred noise in LSB.
    """
    resolution_bits: int = 12
    v_ref: float = 3.3         # V
    v_min: float = 0.0         # V
    v_max: float = 3.3         # V
    sample_rate_hz: float = 100.0  # 100 Hz — 10 ms between samples
    enob: float = 10.5         # effective bits (ESP32 ADC is ~9-11 ENOB)
    input_noise_lsb: float = 2.0   # LSB of noise


class ADCModel:
    """Behavioral ADC model.
    
    Converts continuous voltage signals to discrete digital codes
    with realistic quantisation, noise, and sampling effects.
    """
    
    def __init__(self, params: Optional[ADCParams] = None):
        self.params = params or ADCParams()
        self._n_levels = 2 ** self.params.resolution_bits
        self._lsb = (self.params.v_max - self.params.v_min) / self._n_levels
    
    @property
    def lsb_voltage(self) -> float:
        """LSB voltage (V)."""
        return self._lsb
    
    @property
    def n_levels(self) -> int:
        """Number of quantisation levels."""
        return self._n_levels
    
    def convert(self, V: np.ndarray,
                add_noise: bool = True,
                rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """Convert voltage array to ADC counts.
        
        Args:
            V: Input voltage array (V).
            add_noise: Whether to add quantisation/input noise.
            rng: Random number generator.
        
        Returns:
            Array of integer ADC codes (0 to 2^N − 1).
        """
        if rng is None:
            rng = np.random.default_rng()
        
        p = self.params
        
        # Clamp input
        V_clamped = np.clip(V, p.v_min, p.v_max - self._lsb)
        
        # Add input-referred noise
        if add_noise:
            noise_v = rng.normal(0, p.input_noise_lsb * self._lsb, len(V))
            V_clamped = V_clamped + noise_v
            V_clamped = np.clip(V_clamped, p.v_min, p.v_max - self._lsb)
        
        # Quantise
        codes = np.floor((V_clamped - p.v_min) / self._lsb).astype(np.int32)
        codes = np.clip(codes, 0, self._n_levels - 1)
        
        return codes
    
    def codes_to_voltage(self, codes: np.ndarray) -> np.ndarray:
        """Convert ADC codes back to voltage (for verification).
        
        Args:
            codes: ADC code array.
        
        Returns:
            Reconstructed voltage array (V).
        """
        return self.params.v_min + codes * self._lsb + self._lsb / 2
    
    def sample(self, V: np.ndarray, t: np.ndarray,
               add_noise: bool = True,
               rng_seed: Optional[int] = None) -> dict:
        """Sample a continuous-time signal at the ADC rate.
        
        Args:
            V: Continuous voltage signal.
            t: Time array (seconds) corresponding to V.
            add_noise: Whether to add noise.
            rng_seed: Random seed.
        
        Returns:
            Dictionary with sampled time, codes, and voltages.
        """
        rng = np.random.default_rng(rng_seed)
        p = self.params
        
        # Create sample times
        t_sample = np.arange(t[0], t[-1], 1.0 / p.sample_rate_hz)
        
        # Interpolate voltage at sample times
        V_sampled = np.interp(t_sample, t, V)
        
        # Convert to codes
        codes = self.convert(V_sampled, add_noise=add_noise, rng=rng)
        
        # Reconstructed voltage
        V_reconstructed = self.codes_to_voltage(codes)
        
        return {
            't': t_sample,
            'codes': codes,
            'V_sampled': V_sampled,
            'V_reconstructed': V_reconstructed,
            'lsb': self._lsb,
            'n_samples': len(t_sample),
        }


# ---------------------------------------------------------------------------
# Standalone demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    
    # Generate a slowly rising voltage (like TIA output during positive test)
    t = np.linspace(0, 60, 10000)  # 60 seconds, high resolution
    V_ideal = 1.65 - 0.0005 * (1.0 / (1.0 + np.exp(-0.2 * (t - 30))))  # small dip
    
    adc = ADCModel()
    result = adc.sample(V_ideal, t, add_noise=True, rng_seed=42)
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    
    ax = axes[0]
    ax.plot(t, V_ideal * 1000, linewidth=1, color='#2ecc71', alpha=0.5,
            label='Continuous (ideal)')
    ax.step(result['t'], result['V_reconstructed'] * 1000, linewidth=1,
            color='#3498db', label=f'ADC ({adc.params.resolution_bits}-bit)')
    ax.set_ylabel('Voltage (mV)', fontsize=11)
    ax.set_title(f'ADC Conversion — {adc.params.resolution_bits}-bit, '
                 f'LSB = {adc.lsb_voltage*1e3:.3f} mV', fontsize=13,
                 fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    ax = axes[1]
    ax.step(result['t'], result['codes'], linewidth=1, color='#9b59b6')
    ax.set_xlabel('Time (s)', fontsize=11)
    ax.set_ylabel('ADC Code', fontsize=11)
    ax.set_title('Raw ADC Codes', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('electronics/adc_model_demo.png', dpi=150, bbox_inches='tight')
    plt.show()
    
    print(f"ADC Model: {adc.params.resolution_bits}-bit, "
          f"{adc.n_levels} levels, "
          f"LSB = {adc.lsb_voltage*1e6:.1f} µV, "
          f"Fs = {adc.params.sample_rate_hz} Hz")
    print(f"Sampled {result['n_samples']} points")
