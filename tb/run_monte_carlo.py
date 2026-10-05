import sys
import os
import json
import numpy as np
import subprocess
from tqdm import tqdm
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from biology.assay_simulator import (
    run_assay, AssayConfiguration, LAMPParameters, CRISPRParameters, FluorescenceParameters
)
from electronics.stimulus_generator import StimulusGenerator, StimulusMetadata
from electronics.optical_frontend import OpticalFrontendParams
from electronics.adc_model import ADCParams

def run_iverilog_sim(class_mode: int):
    """Run the RTL simulation with the given class_mode and return the result."""
    # Run Icarus Verilog
    cmd = [
        "vvp",
        "tb/waveforms/sim.vvp",
        f"+CLASS_MODE={class_mode}"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    output = result.stdout
    # Parse the output for RESULT: POSITIVE / NEGATIVE / INVALID / INDETERMINATE
    for line in output.split("\n"):
        if "RESULT:" in line:
            if "POSITIVE" in line: return "POSITIVE"
            elif "NEGATIVE" in line: return "NEGATIVE"
            elif "INVALID" in line: return "INVALID"
            elif "INDETERMINATE" in line: return "INDETERMINATE"
            
    return "UNKNOWN"


def generate_trial(target_present: bool, seed: int):
    """Generate biological and sensor stimulus for a single Monte Carlo trial."""
    rng = np.random.default_rng(seed)
    
    # 1. Biological Variations
    # ------------------------
    k_a = rng.uniform(0.2, 0.5) if target_present else rng.uniform(0.01, 0.05)
    conc = rng.uniform(0.1, 1.0) if target_present else 0.0
    k_cleave = rng.uniform(0.15, 0.3)
    
    lamp_p = LAMPParameters(k_a=k_a)
    crispr_p = CRISPRParameters(k_r=k_cleave)
    fluo_p = FluorescenceParameters(noise_std=rng.uniform(0.01, 0.05))
    
    config = AssayConfiguration(
        target_present=target_present,
        target_concentration=conc
    )
    
    assay = run_assay(config, lamp_params=lamp_p, crispr_params=crispr_p, fluo_params=fluo_p, add_noise=True, rng_seed=seed)
    
    # 2. Electronic / Sensor Variations
    # ---------------------------------
    # Vary ambient light from 50 nW to 200 nW
    ambient = rng.uniform(50e-9, 200e-9)
    # Vary ADC noise from 1 LSB to 5 LSB
    adc_noise = rng.uniform(1.0, 5.0)
    
    frontend_p = OpticalFrontendParams(ambient_power=ambient)
    adc_p = ADCParams(input_noise_lsb=adc_noise)
    
    gen = StimulusGenerator(frontend_params=frontend_p, adc_params=adc_p)
    
    # Generate stimulus
    fluo_curve = assay['fluorescence']['F_noisy']
    t_crispr = assay['crispr']['t']
    
    stim = gen.generate_from_fluorescence(t_crispr, fluo_curve, add_noise=True, rng_seed=seed)
    
    # We will write to the standard tb/stimuli/positive paths so the unmodified testbench finds it
    # We just overwrite it for each trial.
    gen.write_hex_file(stim['adc']['codes'], 'tb/stimuli/positive/optical_adc.hex', bits=12)
    # Also write temp stimulus just to be safe
    thermal = assay['thermal']
    temp_stim = gen.generate_temperature_stimulus(thermal['t'], thermal['T'])
    gen.write_hex_file(temp_stim['adc']['codes'], 'tb/stimuli/positive/temp_adc.hex', bits=12)
    

def main():
    N_TRIALS = 40  # 20 positive, 20 negative
    
    print("=================================================================")
    print("  HYBRID-LAB Monte Carlo Robustness Study")
    print(f"  Running {N_TRIALS} virtual trials per DSP mode")
    print("=================================================================\n")
    
    # Ensure simulator is compiled
    print("Compiling RTL...")
    subprocess.run([
        "iverilog", "-g2012", "-o", "tb/waveforms/sim.vvp",
        "tb/tb_lab_on_chip.sv",
        "rtl/lab_on_chip_top.sv", "rtl/reaction_fsm.sv",
        "rtl/thermal_controller.sv", "rtl/optical_acquisition.sv",
        "rtl/digital_filter.sv", "rtl/baseline_estimator.sv",
        "rtl/decision_engine.sv"
    ], check=True)
    
    modes = {
        0: "Simple Threshold",
        1: "Slope-Based",
        2: "Adaptive Baseline + Threshold"
    }
    
    results = {mode: {'TP': 0, 'TN': 0, 'FP': 0, 'FN': 0, 'INV': 0} for mode in modes}
    
    rng = np.random.default_rng(42)
    seeds = rng.integers(0, 100000, size=N_TRIALS)
    ground_truths = [True]*int(N_TRIALS/2) + [False]*int(N_TRIALS/2)
    
    for i, (seed, target_present) in enumerate(tqdm(zip(seeds, ground_truths), total=N_TRIALS, desc="Simulating Trials")):
        
        # 1. Generate unique biological / physical stimulus
        # We suppress prints from stimulus generator by redirecting stdout temporarily
        devnull = open(os.devnull, 'w')
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            generate_trial(target_present, int(seed))
        finally:
            sys.stdout = old_stdout
            devnull.close()
            
        # 2. Run RTL simulation for each DSP mode
        for mode in modes.keys():
            rtl_result = run_iverilog_sim(mode)
            
            if rtl_result == "INVALID" or rtl_result == "UNKNOWN":
                results[mode]['INV'] += 1
            elif target_present and rtl_result == "POSITIVE":
                results[mode]['TP'] += 1
            elif target_present and rtl_result == "NEGATIVE":
                results[mode]['FN'] += 1
            elif not target_present and rtl_result == "NEGATIVE":
                results[mode]['TN'] += 1
            elif not target_present and rtl_result == "POSITIVE":
                results[mode]['FP'] += 1

    # 3. Print Report
    print("\n\n=================================================================")
    print("  Monte Carlo Results (Simulated Analytical Performance)")
    print("=================================================================")
    
    for mode, name in modes.items():
        r = results[mode]
        tp, tn, fp, fn, inv = r['TP'], r['TN'], r['FP'], r['FN'], r['INV']
        
        sens = tp / (tp + fn) if (tp + fn) > 0 else 0
        spec = tn / (tn + fp) if (tn + fp) > 0 else 0
        
        print(f"\nMode {mode}: {name}")
        print(f"  True Positive:  {tp}")
        print(f"  True Negative:  {tn}")
        print(f"  False Positive: {fp}")
        print(f"  False Negative: {fn}")
        print(f"  Invalid:        {inv}")
        print(f"  --> Sensitivity: {sens*100:.1f}%")
        print(f"  --> Specificity: {spec*100:.1f}%")
        
    print("\n=================================================================")

if __name__ == "__main__":
    main()
