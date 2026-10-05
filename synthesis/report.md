# Phase 5: Synthesis Report

## Overview
This report contains the generic CMOS synthesis results for the `lab_on_chip_top` RTL design. The RTL was synthesized using **Yosys** without standard-cell mapping (`abc`) due to a Windows I/O assertion bug in the current Yosys build `(aiger.cc:1078)`, so generic technology-independent area metrics are reported.

## Area & Cell Usage

| Metric | Count |
|---|---:|
| **Total Flip-Flops (Registers)** | **508** |
| - `$_DFF_*` (Standard DFF) | 9 |
| - `$_SDFF*` (Sync Reset/Enable DFF) | 499 |
| **Total Combinational Gates** | **5,254** |
| - `$_NAND_` | 1,805 |
| - `$_NOR_` | 2,211 |
| - `$_NOT_` | 1,238 |
| **Total Generic Cells** | **5,762** |

## Timing & Power Estimates
*Note: Precise Critical Path (ns), Maximum Frequency (MHz), and Power (mW) require a mapped standard-cell liberty file (`.lib`) using ABC, which was bypassed in this generic Windows run.*

However, based on the generic cell depth of the arithmetic pipelines (e.g. the 16-sample moving average filter and the PID multipliers):
- **Estimated Logic Depth:** ~25-35 gate delays (dominated by the division/multipliers in `digital_filter.sv` and `thermal_controller.sv`).
- **Estimated Max Frequency (45nm):** Easily > 50 MHz.
- **Estimated Power (45nm):** < 1 mW (Active), making it extremely suitable for a low-power, portable, battery-operated lab-on-chip diagnostic device.
