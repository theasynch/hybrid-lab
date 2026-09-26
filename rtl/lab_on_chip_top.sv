// ============================================================================
// lab_on_chip_top.sv — Top-Level Integration of the Lab-on-Chip ASIC
// ============================================================================
//
// This is the top-level module that instantiates and connects all
// RTL subsystems of the LAMP-CRISPR lab-on-chip diagnostic controller.
//
// Architecture (from Simulation Plan, Section 26):
//
//     ┌──────────────────────────────────────────────────────┐
//     │                   lab_on_chip_top                    │
//     │                                                      │
//     │  ┌──────────────┐    ┌─────────────────────┐        │
//     │  │ reaction_fsm │───→│ thermal_controller   │→ PWM   │
//     │  │              │    │                     │        │
//     │  │              │    └─────────────────────┘        │
//     │  │              │                                    │
//     │  │              │───→┌─────────────────────┐        │
//     │  │              │    │ optical_acquisition  │→ LED   │
//     │  │              │    │                     │        │
//     │  └──────┬───────┘    └──────────┬──────────┘        │
//     │         │                       │                    │
//     │         │              ┌────────▼─────────┐         │
//     │         │              │ digital_filter    │         │
//     │         │              └────────┬──────────┘         │
//     │         │              ┌────────▼─────────┐         │
//     │         │              │baseline_estimator │         │
//     │         │              └────────┬──────────┘         │
//     │         │              ┌────────▼─────────┐         │
//     │         └─────────────→│ decision_engine   │→ RESULT│
//     │                        └──────────────────┘         │
//     └──────────────────────────────────────────────────────┘
//
// External interfaces:
//     - Temperature ADC input (SPI/parallel from external ADC)
//     - Optical ADC input (SPI/parallel from external ADC)
//     - Heater PWM output
//     - LED enable output
//     - Cartridge detect input
//     - User start/abort buttons
//     - Result status outputs (active-high LEDs or register)
//     - State debug output (4-bit)
//
// Parameters propagated to submodules; see individual modules.
// ============================================================================

module lab_on_chip_top #(
    parameter DATA_WIDTH       = 12,
    parameter PWM_WIDTH        = 10,
    parameter CLK_FREQ_HZ      = 50_000_000,
    parameter FILTER_WINDOW_LOG2 = 3,
    parameter BASELINE_LOG2    = 4,
    parameter SETTLE_CYCLES    = 100,

    // Timing (ms)
    parameter PREHEAT_MS       = 30_000,
    parameter LAMP_MS          = 1_800_000,
    parameter TRANSFER_MS      = 5_000,
    parameter CRISPR_MS        = 900_000,
    parameter READ_INTERVAL_MS = 10_000,

    // Temperature setpoints (ADC codes)
    parameter LAMP_TEMP_CODE   = 12'd2583,
    parameter CRISPR_TEMP_CODE = 12'd1516,

    // Decision thresholds
    parameter THRESHOLD_POS    = 12'd150,
    parameter THRESHOLD_NEG    = 12'd30,
    parameter SLOPE_THRESHOLD  = 12'd5,
    parameter NOISE_MULTIPLIER = 4'd5
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // ── User interface ─────────────────────────────────────────────
    input  logic                    btn_start,
    input  logic                    btn_abort,
    input  logic                    cartridge_in,

    // ── Classification mode ────────────────────────────────────────
    input  logic [1:0]              class_mode,   // 0=threshold,1=slope,2=adaptive

    // ── Temperature ADC interface ──────────────────────────────────
    input  logic [DATA_WIDTH-1:0]   temp_adc_data,
    input  logic                    temp_adc_valid,

    // ── Optical ADC interface ──────────────────────────────────────
    input  logic [DATA_WIDTH-1:0]   optical_adc_data,
    input  logic                    optical_adc_valid,
    output logic                    optical_adc_start,

    // ── Actuator outputs ───────────────────────────────────────────
    output logic [PWM_WIDTH-1:0]    heater_pwm,
    output logic                    led_en,

    // ── Result outputs ─────────────────────────────────────────────
    output logic [1:0]              result_code,  // 00=NEG,01=POS,10=INDET,11=INVALID
    output logic                    result_ready,

    // ── Status / debug ─────────────────────────────────────────────
    output logic [3:0]              fsm_state,
    output logic                    temp_valid,
    output logic                    temp_fault,
    output logic                    baseline_locked,
    output logic                    fault
);

    // ════════════════════════════════════════════════════════════════
    // Internal wires
    // ════════════════════════════════════════════════════════════════

    // FSM → thermal controller
    logic [DATA_WIDTH-1:0] fsm_temp_setpoint;

    // FSM → optical acquisition
    logic fsm_optical_trigger;
    logic optical_busy;

    // Optical acquisition → digital filter
    logic [DATA_WIDTH-1:0] diff_signal;
    logic                  diff_valid;

    // Digital filter → baseline estimator
    logic [DATA_WIDTH-1:0] filtered_signal;
    logic                  filtered_valid;

    // Baseline estimator → decision engine
    logic [DATA_WIDTH-1:0] corrected_signal;
    logic                  corrected_valid;
    logic [DATA_WIDTH-1:0] baseline_mean;
    logic [DATA_WIDTH-1:0] noise_estimate;

    // FSM → decision engine
    logic reaction_done;

    // Decision engine → FSM
    logic [1:0] decision_result_w;
    logic       decision_valid_w;

    // Thermal controller status
    logic temp_valid_w;
    logic temp_fault_w;

    assign temp_valid = temp_valid_w;
    assign temp_fault = temp_fault_w;

    // ════════════════════════════════════════════════════════════════
    // 1. REACTION FSM — Master sequencer
    // ════════════════════════════════════════════════════════════════
    reaction_fsm #(
        .CLK_FREQ_HZ     (CLK_FREQ_HZ),
        .PREHEAT_MS       (PREHEAT_MS),
        .LAMP_MS          (LAMP_MS),
        .TRANSFER_MS      (TRANSFER_MS),
        .CRISPR_MS        (CRISPR_MS),
        .READ_INTERVAL_MS (READ_INTERVAL_MS),
        .DATA_WIDTH       (DATA_WIDTH),
        .LAMP_TEMP_CODE   (LAMP_TEMP_CODE),
        .CRISPR_TEMP_CODE (CRISPR_TEMP_CODE)
    ) u_reaction_fsm (
        .clk             (clk),
        .rst_n           (rst_n),
        .start           (btn_start),
        .abort           (btn_abort),
        .cartridge_in    (cartridge_in),
        .temp_valid      (temp_valid_w),
        .temp_fault      (temp_fault_w),
        .temp_setpoint   (fsm_temp_setpoint),
        .optical_trigger (fsm_optical_trigger),
        .optical_done    (diff_valid),
        .reaction_done   (reaction_done),
        .decision_result (decision_result_w),
        .decision_valid  (decision_valid_w),
        .state_out       (fsm_state),
        .result_code     (result_code),
        .result_ready    (result_ready),
        .fault           (fault)
    );

    // ════════════════════════════════════════════════════════════════
    // 2. THERMAL CONTROLLER — PID heater control
    // ════════════════════════════════════════════════════════════════
    thermal_controller #(
        .DATA_WIDTH  (DATA_WIDTH),
        .PWM_WIDTH   (PWM_WIDTH)
    ) u_thermal_ctrl (
        .clk         (clk),
        .rst_n       (rst_n),
        .temp_adc    (temp_adc_data),
        .setpoint    (fsm_temp_setpoint),
        .update      (temp_adc_valid),
        .heater_pwm  (heater_pwm),
        .temp_valid  (temp_valid_w),
        .temp_fault  (temp_fault_w)
    );

    // ════════════════════════════════════════════════════════════════
    // 3. OPTICAL ACQUISITION — LED on/off differential measurement
    // ════════════════════════════════════════════════════════════════
    optical_acquisition #(
        .DATA_WIDTH    (DATA_WIDTH),
        .SETTLE_CYCLES (SETTLE_CYCLES)
    ) u_optical_acq (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (fsm_optical_trigger),
        .busy        (optical_busy),
        .adc_data    (optical_adc_data),
        .adc_valid   (optical_adc_valid),
        .adc_start   (optical_adc_start),
        .led_en      (led_en),
        .diff_out    (diff_signal),
        .diff_valid  (diff_valid)
    );

    // ════════════════════════════════════════════════════════════════
    // 4. DIGITAL FILTER — Moving-average noise rejection
    // ════════════════════════════════════════════════════════════════
    digital_filter #(
        .DATA_WIDTH  (DATA_WIDTH),
        .WINDOW_LOG2 (FILTER_WINDOW_LOG2)
    ) u_filter (
        .clk          (clk),
        .rst_n        (rst_n),
        .sample_valid (diff_valid),
        .sample_in    (diff_signal),
        .avg_out      (filtered_signal),
        .avg_valid    (filtered_valid)
    );

    // ════════════════════════════════════════════════════════════════
    // 5. BASELINE ESTIMATOR — Baseline subtraction
    // ════════════════════════════════════════════════════════════════
    baseline_estimator #(
        .DATA_WIDTH    (DATA_WIDTH),
        .BASELINE_LOG2 (BASELINE_LOG2)
    ) u_baseline (
        .clk             (clk),
        .rst_n           (rst_n),
        .sample_in       (filtered_signal),
        .sample_valid    (filtered_valid),
        .corrected_out   (corrected_signal),
        .corrected_valid (corrected_valid),
        .baseline_mean   (baseline_mean),
        .noise_est       (noise_estimate),
        .baseline_locked (baseline_locked)
    );

    // ════════════════════════════════════════════════════════════════
    // 6. DECISION ENGINE — Classification
    // ════════════════════════════════════════════════════════════════
    decision_engine #(
        .DATA_WIDTH       (DATA_WIDTH),
        .THRESHOLD_POS    (THRESHOLD_POS),
        .THRESHOLD_NEG    (THRESHOLD_NEG),
        .SLOPE_THRESHOLD  (SLOPE_THRESHOLD),
        .NOISE_MULTIPLIER (NOISE_MULTIPLIER)
    ) u_decision (
        .clk             (clk),
        .rst_n           (rst_n),
        .fluorescence    (corrected_signal),
        .fluor_valid     (corrected_valid),
        .temp_valid      (temp_valid_w),
        .temp_fault      (temp_fault_w),
        .reaction_done   (reaction_done),
        .noise_est       (noise_estimate),
        .baseline_locked (baseline_locked),
        .mode            (class_mode),
        .result          (decision_result_w),
        .result_valid    (decision_valid_w)
    );

endmodule
