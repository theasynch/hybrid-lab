This is actually a **much better project direction** than spending ₹10–30k on reagents just to get a shaky prototype.

The strongest version is not “we simulated a lab.” It is:

> **We developed a computational digital twin of a portable LAMP–CRISPR lab-on-chip and implemented the electronic control, sensing, signal-processing, and decision-making subsystem in synthesizable RTL.**

That gives your professor something concrete to evaluate: **biology + mathematical model + hardware architecture + RTL + simulation waveforms + quantitative results**.

And yes — we can do almost all of it with free/open tools.

---

# 1. First, an important distinction

There are **three different things** you could mean by “simulate the lab-on-chip.”

### A. Simulate the DNA/RNA biology

Example:

```text
DNA target present
        ↓
LAMP amplification
        ↓
CRISPR-Cas12a recognition
        ↓
Reporter cleavage
        ↓
Fluorescence increases
```

This can be modeled computationally.

### B. Simulate the microfluidic/thermal device

Example:

```text
Sample chamber → extraction → amplification chamber
                              ↓
                         heater profile
                              ↓
                         CRISPR chamber
                              ↓
                         optical chamber
```

This can be simulated as fluid flow, heat transfer and diffusion.

### C. Simulate the actual electronics/RTL

Example:

```text
Temperature ADC
      ↓
Temperature Controller
      ↓
Reaction Sequencer
      ↓
Optical ADC
      ↓
Signal Processing
      ↓
Decision Engine
      ↓
POSITIVE / NEGATIVE
```

This can be simulated **properly in RTL**, producing waveforms exactly like a normal digital-design project.

### And this is where your project becomes interesting:

You can connect **A → B → C computationally**.

---

# 2. The architecture I recommend

I'd call this a **multi-domain digital twin**.

```text
             BIOLOGICAL DOMAIN
 ┌─────────────────────────────────────────┐
 │ Target DNA/RNA sequence                 │
 │             ↓                           │
 │ Primer/guide analysis                   │
 │             ↓                           │
 │ LAMP amplification model                │
 │             ↓                           │
 │ Cas12a recognition model                │
 │             ↓                           │
 │ Reporter cleavage                       │
 │             ↓                           │
 │ Virtual fluorescence signal F(t)        │
 └──────────────────┬──────────────────────┘
                    │
                    ↓
             SENSOR DOMAIN
 ┌─────────────────────────────────────────┐
 │ Optical model                            │
 │ Photodiode + TIA                        │
 │ ADC behavioural model                   │
 │ Temperature sensor model                │
 └──────────────────┬──────────────────────┘
                    │
                    ↓
               RTL DOMAIN
 ┌─────────────────────────────────────────┐
 │ Reaction FSM                             │
 │ Heater Controller                        │
 │ ADC Interface                            │
 │ Digital Filtering                       │
 │ Baseline Correction                     │
 │ Threshold / Decision Engine              │
 │ Error & Control Logic                    │
 │ UART / SPI / I²C                        │
 └──────────────────┬──────────────────────┘
                    │
                    ↓
              DIGITAL RESULT
       ┌──────────────────────────┐
       │ TARGET DETECTED           │
       │ TARGET NOT DETECTED       │
       │ INVALID / REPEAT TEST     │
       └──────────────────────────┘
```

This is **far more defensible** academically than pretending Verilog can somehow simulate molecules.

Verilog simulates the **electronic intelligence of the chip**.

Python/COPASI/etc. simulate the **biological environment that supplies inputs to that electronics**.

---

# 3. Is there one application that does all this?

### No.

And frankly, that's good.

I searched the current ecosystem and there isn't a credible single free program that will take:

> DNA sequence → LAMP enzymology → CRISPR chemistry → microfluidics → photodiode → RTL → GDSII

in one click.

Instead, researchers use specialized tools for different domains.

We can stitch them together.

---

# 4. The software stack I'd use

## Layer 1 — DNA/RNA sequence analysis

### **Benchling**

Benchling provides sequence design and analysis functionality, including DNA/RNA sequence visualization, annotation and in-silico analysis. It also offers academic access. ([benchling.com](https://www.benchling.com/molecular-biology?utm_source=chatgpt.com))

Use it for:

```text
FASTA sequence
      ↓
sequence annotation
      ↓
target region identification
      ↓
primer/guide planning
```

It isn't our biochemical simulator.

It is our **digital biology workspace**.

---

# 5. LAMP primer design

This is one place where you should **not invent your own algorithm immediately**.

### NEB LAMP Primer Design Tool

NEB explicitly provides a LAMP-specific design tool. It accepts a target sequence and produces candidate LAMP primer sets; NEB recommends evaluating multiple candidate sets because in-silico design alone doesn't guarantee experimental performance. ([neb.com](https://www.neb.com/en/tools-and-resources/video-library/neb-lamp-primer-design-tool-tutorial?utm_source=chatgpt.com))

Eiken's PrimerExplorer is another established LAMP-specific tool. LAMP primer design involves four primer types targeting six distinct regions of the target. ([eiken.co.jp](https://www.eiken.co.jp/en/products/lamp/?utm_source=chatgpt.com))

So your pipeline can be:

```text
Target sequence
      ↓
NEB LAMP Designer
      ↓
Candidate primer sets
      ↓
Pick candidate set
      ↓
Use computational model
```

### Important:

The paper should say:

> “The primer sequences were designed in silico.”

Not:

> “The primer set was experimentally validated.”

Those are very different claims.

---

# 6. CRISPR guide analysis

For Cas12a, the Broad Institute's current **CRISPick** platform explicitly supports AsCas12a and related Cas12a enzyme options. It accepts sequences and can rank candidate guides. ([portals.broadinstitute.org](https://portals.broadinstitute.org/gppx/crispick/public?utm_source=chatgpt.com))

Again, there's an important distinction:

CRISPick is primarily a **CRISPR guide-design platform**.

It isn't a complete simulation of a CRISPR diagnostic reaction.

So:

```text
Target region
      ↓
Cas12a-compatible guide candidate
      ↓
PAM compatibility / specificity analysis
      ↓
candidate crRNA
```

For our paper, we'd treat this as **in-silico molecular design**, not experimental proof.

---

# 7. DNA/RNA structure analysis

This is where **NUPACK** becomes very interesting.

NUPACK is specifically designed for computational analysis and design of nucleic-acid systems and can analyze interacting DNA/RNA strands, including mixed DNA/RNA systems. Its current platform supports both sequence analysis and design. ([nupack.org](https://www.nupack.org/?utm_source=chatgpt.com))

That lets your biotech teammate investigate things such as:

```text
Primer / guide candidate
        ↓
secondary structure
        ↓
hairpins
        ↓
interactions
        ↓
possible problematic structures
```

NUPACK can therefore provide **real computational biology outputs** for the paper rather than merely drawing DNA strands.

---

# 8. The really interesting part: simulate the biochemical reaction

This is where I'd use **COPASI + Python**.

COPASI is a biochemical network simulator capable of solving biochemical reaction models using deterministic ODEs as well as stochastic simulation methods such as Gillespie simulations. It also supports parameter scans, optimization and visualization. ([copasi.org](https://copasi.org/?utm_source=chatgpt.com))

This is almost tailor-made for what we need.

We can create an **abstract reaction network**:

```text
Target
   ↓
LAMP amplification
   ↓
Amplicon
   ↓
Cas12a + crRNA + Amplicon
   ↓
Activated Cas12a
   ↓
Reporter cleavage
   ↓
Fluorescent reporter
```

Then COPASI numerically simulates the concentrations over time.

---

# 9. But here's a crucial scientific caveat

We should **not claim**:

> “COPASI exactly simulates the molecular mechanism of LAMP and Cas12a.”

That would be too strong.

LAMP is extraordinarily complicated mechanistically. It involves multiple primers, strand displacement, loop structures, self-priming and branched amplification products.

Instead we'll construct a **reduced-order kinetic model**.

For example:

\[
\frac{dA}{dt}=k_aT A\left(1-\frac{A}{A_{\max}}\right)
\]

where:

- \(T\) = effective target/template availability
- \(A\) = amplified product
- \(k_a\) = effective amplification parameter
- \(A_{\max}\) = saturation/amplification capacity

Then:

\[
\frac{dC}{dt}=k_cA C_{\mathrm{inactive}}
\]

for an effective Cas12a activation model.

And:

\[
\frac{dR}{dt}=-k_r C R
\]

where \(R\) represents intact reporter.

Finally:

\[
F(t)=F_0+\alpha(R_0-R(t))
\]

where \(F(t)\) becomes our **virtual fluorescence signal**.

Notice what we're doing.

We're not saying those equations are the actual complete molecular mechanism.

We're saying:

> “We developed a reduced-order computational model that maps target presence to an expected fluorescence trajectory.”

That's completely legitimate for a **system-level theoretical paper**, provided we clearly identify the model as phenomenological and later validate it experimentally.

---

# 10. And then comes the coolest part

We take this virtual fluorescence curve:

```text
Fluorescence
    │
    │                         _________
    │                     ___/
    │                  __/
    │               __/
    │            __/
    │___________/
    │
    └────────────────────────────── Time
```

and feed it into the RTL testbench.

Now your RTL thinks:

> “I'm receiving fluorescence sensor data from an actual chip.”

It doesn't know that the signal came from Python.

That's **hardware-software co-simulation**.

---

# 11. Your RTL becomes the actual "electronic brain" of the lab-on-chip

I'd divide the RTL into these modules:

### `thermal_controller.sv`

Maintains the reaction temperature.

```text
Temperature ADC
      ↓
 error = T_target - T_actual
      ↓
 PID / controller
      ↓
 Heater PWM
```

---

### `reaction_fsm.sv`

Controls the complete procedure:

```text
IDLE
 ↓
CARTRIDGE_CHECK
 ↓
PREHEAT
 ↓
LAMP
 ↓
TRANSFER
 ↓
CRISPR
 ↓
READ
 ↓
ANALYZE
 ↓
RESULT
```

This is one of the strongest pieces of RTL you can show your professor.

---

### `optical_acquisition.sv`

Receives ADC readings:

```text
LED ON
  ↓
ADC
  ↓
sample

LED OFF
  ↓
ADC
  ↓
sample
```

Then:

\[
S=V_{\mathrm{ON}}-V_{\mathrm{OFF}}
\]

This gives you ambient-light cancellation.

---

### `digital_filter.sv`

Implement:

- moving average
- baseline subtraction
- noise rejection

For example:

\[
Y[n]=\frac{1}{N}\sum_{k=0}^{N-1}X[n-k]
\]

---

### `decision_engine.sv`

Something like:

```text
                         ┌── Positive
                         │
Fluorescence > threshold ┤
                         │
                         └── Negative
```

But realistically:

```text
Target signal
      +
Positive control valid
      +
Temperature valid
      +
Reaction completed
      ↓
     RESULT
```

This is **much better** than a single threshold.

---

# 12. Add an "INVALID" state

This is something I'd strongly recommend.

Real diagnostic systems shouldn't just produce:

```text
YES / NO
```

They should be able to say:

```text
POSITIVE
NEGATIVE
INVALID
```

For example:

```text
Temperature never reached target
                 ↓
              INVALID

Positive control failed
                 ↓
              INVALID

Optical sensor saturated
                 ↓
              INVALID
```

That makes your architecture feel much more like a real instrument.

---

# 13. What software simulates the RTL?

## Option A — Verilator

Very good choice.

## Option B — Icarus Verilog

Simpler for beginners.

## Option C — Cocotb

This is where I'd really go.

Cocotb lets you write your RTL verification environment in **Python** rather than building the entire testbench in SystemVerilog. Its documentation explicitly describes Python-based verification of Verilog/SystemVerilog/VHDL designs. ([docs.cocotb.org](https://docs.cocotb.org/en/development/?utm_source=chatgpt.com))

So your CS team can write:

```python
# biological model
fluorescence = simulate_assay(target_present=True)

# drive into RTL
dut.optical_adc.value = fluorescence

# observe result
assert dut.result.value == POSITIVE
```

That's a **killer interdisciplinary demo**.

---

# 14. Then generate beautiful RTL waveforms

Use **GTKWave**.

It reads standard VCD/FST/GHW waveform files and lets you inspect signals interactively. ([gtkwave.sourceforge.net](https://gtkwave.sourceforge.net/?utm_source=chatgpt.com))

Your final paper can show a figure like:

```text
time ───────────────────────────────────────>

temp_valid       ____██████████████████████

lamp_active      ____████████████████

crispr_active                    ____████████

fluorescence      ________________/██████████

threshold         ----------------------------

result_valid                       ______██████

result_positive                    ______██████
```

That is **actual simulated hardware evidence**.

---

# 15. Then synthesize your RTL

This is where your VLSI background becomes extremely useful.

Use **Yosys**.

Yosys is an open-source Verilog synthesis suite that converts RTL into a synthesized netlist. ([yosyshq.net](https://yosyshq.net/yosys/download.html?utm_source=chatgpt.com))

You can report:

| Metric | Result |
|---|---:|
| RTL modules | X |
| Flip-flops | X |
| Combinational cells | X |
| Critical path | X ns |
| Estimated frequency | X MHz |
| Area | X |
| Power estimate | X |

Now suddenly you've gone from:

> “We have an idea for a biosensor.”

to:

> “We designed and synthesized the digital control ASIC architecture for the biosensor.”

That is a **very different project**.

---

# 16. And you could take it further: RTL → GDSII

This is optional, but knowing your VLSI interests, I think it is worth considering.

OpenROAD is specifically intended to support open-source RTL-to-GDSII physical design and includes synthesis/P&R/STA-related flow infrastructure. ([theopenroadproject.org](https://theopenroadproject.org/welcome-to-openroads-documentation/?utm_source=chatgpt.com))

So:

```text
SystemVerilog
       ↓
Verilator simulation
       ↓
Cocotb verification
       ↓
Yosys synthesis
       ↓
OpenROAD
       ↓
Physical Design
       ↓
GDSII
```

Now you have an actual **ASIC implementation of the electronic subsystem**.

Not the biochemical reaction itself.

That's an important distinction.

---

# 17. What about the actual microfluidic lab-on-chip?

This is the part where people usually overpromise.

COMSOL has a dedicated Microfluidics Module capable of modelling laminar flow, multiphase flow, porous media, heat transfer and related phenomena relevant to lab-on-chip devices. ([comsol.com](https://www.comsol.com/microfluidics-module?utm_source=chatgpt.com))

But COMSOL is commercial software.

Before spending money, check whether **VIT has a license**.

If it does:

### This becomes fantastic.

You design something like:

```text
 ┌───────────────────────────────────────────┐
 │                                           │
 │ SAMPLE                                    │
 │   ↓                                       │
 │ [Lysis] → [Extraction] → [LAMP]           │
 │                               ↓           │
 │                         [Transfer valve]   │
 │                               ↓           │
 │                          [CRISPR]         │
 │                               ↓           │
 │                         [Detection]       │
 │                               ↓           │
 │                            WASTE          │
 └───────────────────────────────────────────┘
```

Then simulate:

- Channel flow
- Mixing
- Residence time
- Thermal distribution
- Chamber heating
- Fluid transfer
- Diffusion

COMSOL explicitly describes modelling lab-on-chip devices, micromixers, channels, micropumps and coupled heat/mass transport. ([comsol.com](https://www.comsol.com/microfluidics-module?utm_source=chatgpt.com))

---

# 18. If VIT doesn't have COMSOL

Don't panic.

We can build the physical model ourselves using:

### Python

for:

- diffusion
- reaction
- thermal modelling
- concentration profiles

or

### OpenModelica

OpenModelica is an open-source modelling and simulation environment intended for academic and engineering use. ([openmodelica.org](https://openmodelica.org/?utm_source=chatgpt.com))

or, for more advanced PDE modelling:

### FEniCSx

FEniCSx is an open-source finite-element framework and current releases are available for scientific simulation. ([fenicsproject.org](https://fenicsproject.org/download/?utm_source=chatgpt.com))

But honestly, **don't make CFD the centerpiece** unless someone on the team already knows it.

It can eat your entire semester.

---

# 19. The complete free/low-cost toolchain I'd recommend

Here's my preferred architecture:

| Layer | Tool | Purpose |
|---|---|---|
| DNA sequence | Benchling | Sequence visualization/analysis |
| LAMP design | NEB LAMP Designer / PrimerExplorer | LAMP primer candidates |
| CRISPR design | CRISPick | Cas12a guide candidates |
| DNA/RNA structure | NUPACK | Secondary/intermolecular analysis |
| Biochemical model | **COPASI** | Reduced-order reaction kinetics |
| Biological simulation | **Python** | Assay model + fluorescence generation |
| Thermal model | Python / OpenModelica | Heater/chamber behaviour |
| Optical circuit | **LTspice** | Photodiode/TIA analogue front-end |
| PCB | **KiCad** | Optional physical electronics design |
| RTL | **SystemVerilog** | Electronic architecture |
| RTL simulation | **Verilator / Icarus** | Simulation |
| Verification | **Cocotb** | Python-driven testbench |
| Waveforms | **GTKWave** | Simulation evidence |
| Synthesis | **Yosys** | RTL → netlist |
| Physical design | **OpenROAD** | Netlist → layout/GDSII |
| Microfluidics | COMSOL / FEniCSx | Optional advanced simulation |
| Scientific visualization | Python/Matplotlib | Figures/results |

KiCad itself is open-source and includes schematic capture, PCB layout and an integrated SPICE simulator. ([kicad.org](https://www.kicad.org/?utm_source=chatgpt.com)) LTspice is currently available as a free SPICE simulator with schematic capture and waveform viewing. ([analog.com](https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html?utm_source=chatgpt.com))

---

# 20. This gives us an absolutely killer simulation experiment

Imagine your final demo.

You select:

```text
TARGET = PRESENT
```

The Python biological model generates:

```text
0 min       fluorescence = 0.10
5 min       fluorescence = 0.11
10 min      fluorescence = 0.12
15 min      fluorescence = 0.18
20 min      fluorescence = 0.42
25 min      fluorescence = 0.81
30 min      fluorescence = 1.27
```

Your simulated optical front-end converts that into ADC counts.

Then:

```text
Python
  ↓
virtual ADC
  ↓
RTL
  ↓
digital filter
  ↓
threshold engine
  ↓
POSITIVE
```

Then run:

```text
TARGET = ABSENT
```

and obtain:

```text
fluorescence ≈ baseline
          ↓
       NEGATIVE
```

Then introduce:

```text
TEMPERATURE FAULT
```

and obtain:

```text
           INVALID
```

That is a **proper validation suite**.

---

# 21. Even better: perform a Monte Carlo study

This is where your paper becomes much more research-like.

Don't run just:

```text
positive → positive
negative → negative
```

Run **hundreds or thousands of virtual trials**.

Introduce variation in:

- Starting target concentration
- Amplification rate
- Cas12a activity
- Optical noise
- LED intensity
- Ambient light
- ADC quantization
- Temperature error
- Baseline drift
- Reporter concentration

Then ask:

> How robust is our decision algorithm?

For example:

```text
1000 simulated tests

True Positive:   471
True Negative:   486
False Positive:   12
False Negative:   21
Invalid:          10
```

Then calculate:

\[
Sensitivity=
\frac{TP}{TP+FN}
\]

\[
Specificity=
\frac{TN}{TN+FP}
\]

Again, these would be **simulation metrics**, not clinical sensitivity/specificity.

We would label them:

> *simulated analytical classification performance*

not:

> *clinical diagnostic accuracy.*

That distinction is extremely important.

---

# 22. We can also do an experiment nobody else on your team is probably thinking about

### Stress-test the chip.

For example:

### Temperature perturbation

```text
Target: 65°C

Simulation:
60°C
61°C
62°C
...
70°C
```

Determine how reaction timing theoretically changes.

### Optical noise

```text
SNR = 40 dB
SNR = 30 dB
SNR = 20 dB
SNR = 10 dB
```

Determine when classification starts failing.

### Low-concentration target

Reduce initial target concentration and see how your model's time-to-positive changes.

### Power budget

Simulate:

```text
Heater
+
MCU
+
LED
+
TIA
+
ADC
```

and estimate battery endurance.

Now your paper isn't merely:

> "Here's our architecture."

It becomes:

> **"Here is our architecture, mathematical model, RTL implementation, verification methodology, sensitivity analysis and system-level performance study."**

That's a dramatically stronger paper.

---

# 23. And there is an especially cool CS contribution

We can make the **signal interpretation algorithm configurable**.

For example, implement three modes:

### Mode 1 — Simple threshold

\[
F > F_{th}
\]

### Mode 2 — slope-based

\[
\frac{dF}{dt}>S_{th}
\]

### Mode 3 — adaptive baseline + threshold

```text
baseline estimation
        ↓
noise estimation
        ↓
adaptive threshold
        ↓
classification
```

Then compare them.

This creates an actual research question:

> **Which lightweight digital signal-processing strategy provides the highest classification robustness under simulated sensor noise while remaining suitable for low-resource embedded hardware?**

Boom.

Now the CS side has a genuine technical contribution.

---

# 24. And your electronics contribution becomes even stronger

Your optical subsystem could be:

```text
Blue LED
   ↓
Reaction chamber
   ↓
Emission filter
   ↓
Photodiode
   ↓
TIA
   ↓
ADC
   ↓
RTL
```

We can simulate the TIA in LTspice.

Then give the resulting sensor waveform to Verilog.

So you have:

**SPICE → RTL → biological model**

rather than three disconnected simulations.

---

# 25. What I would NOT do

There are three traps I'd avoid.

### Don't attempt full molecular dynamics.

You absolutely do not need to simulate individual polymerase molecules, Cas12a conformational changes, molecular collisions, etc.

That is an entirely different research project.

### Don't build a massive microfluidics CFD model first.

Your core contribution is the **portable diagnostic architecture**.

### Don't invent fake experimental results.

This is the biggest one.

Your paper should clearly distinguish:

```text
Literature-derived parameters
        ↓
Assumptions
        ↓
Computational model
        ↓
Simulation results
        ↓
Future experimental validation
```

That is academically honest and actually stronger.

---

# 26. Here's the project I think you should actually pursue

I would rename the project slightly:

> **A Computationally Validated RTL Architecture for a Portable LAMP–CRISPR Lab-on-Chip Molecular Detection System**

And make the final system:

```text
                 ┌──────────────────────┐
                 │   TARGET SEQUENCE     │
                 └──────────┬───────────┘
                            ↓
                  IN-SILICO BIOLOGY
                  ┌─────────────────┐
                  │ Primer analysis │
                  │ Guide analysis  │
                  │ NUPACK analysis │
                  └────────┬────────┘
                           ↓
                    BIOCHEMICAL MODEL
                  ┌──────────────────┐
                  │ LAMP model       │
                  │ Cas12a model     │
                  │ Reporter model   │
                  └────────┬─────────┘
                           ↓
                  VIRTUAL SENSOR
                  ┌──────────────────┐
                  │ Fluorescence     │
                  │ Temperature      │
                  │ Noise            │
                  └────────┬─────────┘
                           ↓
                    ANALOG FRONT END
                  ┌──────────────────┐
                  │ Photodiode       │
                  │ TIA              │
                  │ ADC              │
                  └────────┬─────────┘
                           ↓
                     RTL CHIP
      ┌────────────────────────────────────┐
      │ Reaction FSM                       │
      │ Heater Controller                  │
      │ Sensor Interface                  │
      │ Digital Filter                    │
      │ Baseline Estimator                │
      │ Decision Engine                   │
      │ Fault Detection                   │
      │ Communication Interface           │
      └────────────────┬───────────────────┘
                       ↓
                 SYNTHESIS / P&R
                       ↓
                     GDSII
```

That is a **proper interdisciplinary VLSI + biotech project**.

And crucially, **you don't need to purchase Cas12a, Bst polymerase, primers, photodiodes, heaters or even an ESP32 to complete the theoretical/RTL stage.**

---

## And I think we can take this one step further.

Rather than immediately rewriting your paper, **we should build the simulation environment first**.

I would structure the repository like this:

```text
lab-on-chip/
│
├── biology/
│   ├── target_sequence.fasta
│   ├── lamp_model.py
│   ├── crispr_model.py
│   ├── fluorescence_model.py
│   └── results/
│
├── electronics/
│   ├── optical_frontend/
│   └── thermal_model/
│
├── rtl/
│   ├── reaction_fsm.sv
│   ├── thermal_controller.sv
│   ├── optical_acquisition.sv
│   ├── digital_filter.sv
│   ├── decision_engine.sv
│   └── top.sv
│
├── tb/
│   ├── cocotb_test.py
│   └── stimuli/
│
├── synthesis/
│   ├── yosys/
│   └── openroad/
│
└── paper/
    └── ieee_paper.tex
```

Then we can actually **build this from zero**, starting with a completely safe synthetic target sequence, a simplified LAMP/CRISPR kinetic model, and a Python-generated fluorescence waveform, and feed that waveform into a real SystemVerilog RTL design. That is the point where this stops being an idea and becomes a serious project.
