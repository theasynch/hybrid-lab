"""
RTL Stimulus Generator
=======================

Converts the Python-domain simulation outputs (fluorescence, temperature,
ADC codes) into stimulus files that the SystemVerilog RTL testbench
can read during simulation.

This is the critical bridge between:
    Python (biological + sensor models) → RTL (digital design)

The generated files are plain-text files with one sample per line,
compatible with Verilog's $readmemh() or $readmemb() system tasks,
or Cocotb's Python-based stimulus injection.

Output formats:
    1. .hex  — Hex-encoded ADC codes (for $readmemh)
    2. .bin  — Binary-encoded ADC codes (for $readmemb)
    3. .csv  — Human-readable CSV with time, voltage, code
    4. .json — Complete stimulus metadata for Cocotb

References:
    - Simulation Plan Section 10: "Python → virtual ADC → RTL"
    - Simulation Plan Section 13: Cocotb verification
"""

import sys
import os
import json
import numpy as np
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from electronics.optical_frontend import OpticalFrontend, OpticalFrontendParams
from electronics.adc_model import ADCModel, ADCParams


@dataclass
class StimulusMetadata:
    """Metadata for generated stimulus files.
    
    Stored alongside the stimulus data for traceability.
    """
    assay_name: str = ""
    target_present: bool = True
    target_concentration: float = 1.0
    adc_bits: int = 12
    sample_rate_hz: float = 100.0
    n_samples: int = 0
    timestamp: str = ""
    generator_version: str = "1.0.0"


class StimulusGenerator:
    """Generates RTL-compatible stimulus files from simulation data."""
    
    def __init__(self,
                 frontend_params: Optional[OpticalFrontendParams] = None,
                 adc_params: Optional[ADCParams] = None):
        self.frontend = OpticalFrontend(frontend_params)
        self.adc = ADCModel(adc_params)
    
    def generate_from_fluorescence(self,
                                    t_min: np.ndarray,
                                    F: np.ndarray,
                                    add_noise: bool = True,
                                    rng_seed: Optional[int] = None,
                                    ) -> dict:
        """Convert fluorescence signal to ADC stimulus.
        
        Pipeline:
            F(t) → OpticalFrontend → V_TIA → ADC → digital codes
        
        Args:
            t_min: Time array (minutes).
            F: Fluorescence array (AU).
            add_noise: Whether to add sensor noise.
            rng_seed: Random seed.
        
        Returns:
            Dictionary with all intermediate signals and final codes.
        """
        rng = np.random.default_rng(rng_seed)
        
        # Step 1: Optical frontend (fluorescence → differential voltage)
        optical = self.frontend.measure_differential(
            F, add_noise=add_noise, rng_seed=rng_seed
        )
        
        # Step 2: ADC conversion (voltage → codes)
        t_seconds = t_min * 60.0
        adc_result = self.adc.sample(
            optical['S'], t_seconds,
            add_noise=add_noise, rng_seed=rng_seed
        )
        
        return {
            'optical': optical,
            'adc': adc_result,
            't_min': t_min,
            'F_input': F,
        }
    
    def generate_temperature_stimulus(self,
                                       t_seconds: np.ndarray,
                                       T: np.ndarray,
                                       T_range: tuple = (0.0, 100.0),
                                       ) -> dict:
        """Convert temperature profile to ADC stimulus.
        
        Models a temperature sensor (NTC/RTD) → ADC path.
        
        Args:
            t_seconds: Time array (seconds).
            T: Temperature array (°C).
            T_range: Sensor mapping range (min_°C, max_°C).
        
        Returns:
            Dictionary with temperature ADC codes.
        """
        # Linear mapping: T → voltage → ADC
        T_min, T_max = T_range
        V = self.adc.params.v_min + (T - T_min) / (T_max - T_min) * (
            self.adc.params.v_max - self.adc.params.v_min)
        V = np.clip(V, self.adc.params.v_min, self.adc.params.v_max)
        
        adc_result = self.adc.sample(V, t_seconds, add_noise=True)
        
        return {
            't': t_seconds,
            'T': T,
            'V': V,
            'adc': adc_result,
        }
    
    def write_hex_file(self, codes: np.ndarray, filepath: str,
                       bits: int = 12):
        """Write ADC codes as hex file for $readmemh().
        
        Args:
            codes: Array of integer ADC codes.
            filepath: Output file path.
            bits: Bit width for formatting.
        """
        hex_width = (bits + 3) // 4  # hex digits needed
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w') as f:
            for code in codes:
                f.write(f"{int(code):0{hex_width}X}\n")
        print(f"  Written {len(codes)} hex codes to {filepath}")
    
    def write_binary_file(self, codes: np.ndarray, filepath: str,
                           bits: int = 12):
        """Write ADC codes as binary file for $readmemb().
        
        Args:
            codes: Array of integer ADC codes.
            filepath: Output file path.
            bits: Bit width.
        """
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w') as f:
            for code in codes:
                f.write(f"{int(code):0{bits}b}\n")
        print(f"  Written {len(codes)} binary codes to {filepath}")
    
    def write_csv_file(self, t: np.ndarray, codes: np.ndarray,
                        V: np.ndarray, filepath: str):
        """Write human-readable CSV stimulus file.
        
        Args:
            t: Time array.
            codes: ADC code array.
            V: Original voltage array.
            filepath: Output file path.
        """
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w') as f:
            f.write("time_s,adc_code,voltage_v\n")
            for i in range(len(t)):
                f.write(f"{t[i]:.6f},{int(codes[i])},{V[i]:.8f}\n")
        print(f"  Written {len(t)} samples to {filepath}")
    
    def write_cocotb_json(self, result: dict, metadata: StimulusMetadata,
                           filepath: str):
        """Write complete stimulus data as JSON for Cocotb testbench.
        
        Args:
            result: Output from generate_from_fluorescence().
            metadata: Stimulus metadata.
            filepath: Output file path.
        """
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        
        adc = result['adc']
        metadata.n_samples = len(adc['codes'])
        metadata.timestamp = datetime.now().isoformat()
        
        data = {
            'metadata': asdict(metadata),
            'optical_adc': {
                'times_s': adc['t'].tolist(),
                'codes': adc['codes'].tolist(),
                'lsb_v': float(adc['lsb']),
            },
            'fluorescence_input': {
                'times_min': result['t_min'].tolist(),
                'values_au': result['F_input'].tolist(),
            },
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"  Written Cocotb stimulus JSON to {filepath}")
    
    def generate_all_formats(self, result: dict,
                              metadata: StimulusMetadata,
                              output_dir: str):
        """Generate stimulus files in all formats.
        
        Creates:
            output_dir/optical_adc.hex
            output_dir/optical_adc.bin
            output_dir/optical_adc.csv
            output_dir/stimulus.json
        
        Args:
            result: Output from generate_from_fluorescence().
            metadata: Stimulus metadata.
            output_dir: Output directory.
        """
        os.makedirs(output_dir, exist_ok=True)
        
        codes = result['adc']['codes']
        t = result['adc']['t']
        V = result['adc']['V_sampled']
        
        print(f"\nGenerating stimulus files in {output_dir}/")
        
        self.write_hex_file(
            codes,
            os.path.join(output_dir, 'optical_adc.hex'),
            bits=self.adc.params.resolution_bits,
        )
        self.write_binary_file(
            codes,
            os.path.join(output_dir, 'optical_adc.bin'),
            bits=self.adc.params.resolution_bits,
        )
        self.write_csv_file(
            t, codes, V,
            os.path.join(output_dir, 'optical_adc.csv'),
        )
        self.write_cocotb_json(
            result, metadata,
            os.path.join(output_dir, 'stimulus.json'),
        )
        
        print(f"  Total samples: {len(codes)}")
        print(f"  ADC resolution: {self.adc.params.resolution_bits}-bit")
        print(f"  Code range: [{codes.min()}, {codes.max()}]")


# ═══════════════════════════════════════════════════════════════════════
# MAIN — Generate stimulus files from a complete assay simulation
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    from biology.assay_simulator import run_assay, AssayConfiguration
    
    os.makedirs('tb/stimuli', exist_ok=True)
    
    print("=" * 65)
    print("  HYBRID-LAB Stimulus Generator")
    print("  Generating RTL testbench stimulus from biological models")
    print("=" * 65)
    
    gen = StimulusGenerator()
    
    # ── Positive test stimulus ───────────────────────────────────────
    print("\n▶ Generating POSITIVE test stimulus...")
    config_pos = AssayConfiguration(
        name="Positive Stimulus",
        target_present=True,
        target_concentration=1.0,
    )
    assay_pos = run_assay(config_pos, add_noise=True, rng_seed=42)
    
    fluo_pos = assay_pos['fluorescence']
    t_crispr = assay_pos['crispr']['t']
    
    stim_pos = gen.generate_from_fluorescence(
        t_crispr, fluo_pos['F_noisy'],
        add_noise=True, rng_seed=100,
    )
    
    meta_pos = StimulusMetadata(
        assay_name="positive_control",
        target_present=True,
        target_concentration=1.0,
        adc_bits=gen.adc.params.resolution_bits,
        sample_rate_hz=gen.adc.params.sample_rate_hz,
    )
    
    gen.generate_all_formats(stim_pos, meta_pos, 'tb/stimuli/positive')
    
    # ── Negative test stimulus ───────────────────────────────────────
    print("\n▶ Generating NEGATIVE test stimulus...")
    config_neg = AssayConfiguration(
        name="Negative Stimulus",
        target_present=False,
    )
    assay_neg = run_assay(config_neg, add_noise=True, rng_seed=43)
    
    fluo_neg = assay_neg['fluorescence']
    
    stim_neg = gen.generate_from_fluorescence(
        assay_neg['crispr']['t'], fluo_neg['F_noisy'],
        add_noise=True, rng_seed=101,
    )
    
    meta_neg = StimulusMetadata(
        assay_name="negative_control",
        target_present=False,
        target_concentration=0.0,
        adc_bits=gen.adc.params.resolution_bits,
        sample_rate_hz=gen.adc.params.sample_rate_hz,
    )
    
    gen.generate_all_formats(stim_neg, meta_neg, 'tb/stimuli/negative')
    
    # ── Temperature stimulus ─────────────────────────────────────────
    print("\n▶ Generating TEMPERATURE stimulus...")
    thermal = assay_pos['thermal']
    temp_stim = gen.generate_temperature_stimulus(
        thermal['t'], thermal['T'],
    )
    
    gen.write_hex_file(
        temp_stim['adc']['codes'],
        'tb/stimuli/positive/temp_adc.hex',
        bits=gen.adc.params.resolution_bits,
    )
    
    print("\n" + "=" * 65)
    print("  Stimulus generation complete.")
    print("  Files ready for RTL testbench in tb/stimuli/")
    print("=" * 65)
