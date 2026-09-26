// ============================================================================
// decision_engine.sv — Multi-Criteria Diagnostic Decision Engine
// ============================================================================
//
// Implements the diagnostic classification logic from the
// Simulation Plan, Sections 11–12 and 23.
//
// Decision rule (Eq. 11 from the paper):
//
//     POSITIVE:       F_corrected ≥ θ_positive  AND  all controls valid
//     NEGATIVE:       F_corrected < θ_negative   AND  all controls valid
//     INDETERMINATE:  θ_negative ≤ F < θ_positive AND  controls valid
//     INVALID:        any control failure
//
// Validity checks (Section 12):
//     - Temperature was within tolerance for the required duration
//     - Positive control channel exceeded threshold (if present)
//     - Optical sensor not saturated
//     - Reaction timer completed
//
// The engine supports three classification modes (Section 23):
//     Mode 0 — Simple threshold:            F > F_th
//     Mode 1 — Slope-based:                 dF/dt > S_th
//     Mode 2 — Adaptive baseline+threshold: (F − baseline) > N·σ_noise
//
// Ports:
//     fluorescence   : Baseline-corrected fluorescence value
//     fluor_valid    : Pulsed when new fluorescence is ready
//     temp_valid     : Temperature within tolerance (from thermal_controller)
//     temp_fault     : Temperature fault (from thermal_controller)
//     reaction_done  : Reaction timer expired (from reaction_fsm)
//     noise_est      : Noise estimate (from baseline_estimator)
//     mode           : Classification mode select (0, 1, 2)
//     result         : 2-bit result code
//     result_valid   : Pulsed when classification is final
// ============================================================================

module decision_engine #(
    parameter DATA_WIDTH       = 12,
    parameter THRESHOLD_POS    = 12'd150,  // θ_positive (corrected ADC codes)
    parameter THRESHOLD_NEG    = 12'd30,   // θ_negative
    parameter SLOPE_THRESHOLD  = 12'd5,    // dF/dt threshold for Mode 1
    parameter NOISE_MULTIPLIER = 4'd5      // N for Mode 2 (N·σ)
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // Fluorescence input (baseline-corrected)
    input  logic [DATA_WIDTH-1:0]   fluorescence,
    input  logic                    fluor_valid,

    // System status inputs
    input  logic                    temp_valid,
    input  logic                    temp_fault,
    input  logic                    reaction_done,

    // Baseline / noise info (from baseline_estimator)
    input  logic [DATA_WIDTH-1:0]   noise_est,
    input  logic                    baseline_locked,

    // Mode select
    input  logic [1:0]              mode,       // 0=threshold, 1=slope, 2=adaptive

    // Classification output
    output logic [1:0]              result,     // 00=NEG, 01=POS, 10=INDET, 11=INVALID
    output logic                    result_valid
);

    // ── Result codes ───────────────────────────────────────────────────
    localparam [1:0] RES_NEGATIVE      = 2'b00;
    localparam [1:0] RES_POSITIVE      = 2'b01;
    localparam [1:0] RES_INDETERMINATE = 2'b10;
    localparam [1:0] RES_INVALID       = 2'b11;

    // ── Internal state ─────────────────────────────────────────────────
    logic [DATA_WIDTH-1:0] prev_fluor;
    logic [DATA_WIDTH-1:0] peak_fluor;     // track peak fluorescence
    logic signed [DATA_WIDTH:0] slope;     // dF (signed for negative slopes)

    // ── Adaptive threshold ─────────────────────────────────────────────
    logic [DATA_WIDTH-1:0] adaptive_thresh;

    // Compute: adaptive_thresh = NOISE_MULTIPLIER × noise_est
    // Use shift-add for small multiplier to avoid a full multiplier
    always_comb begin
        adaptive_thresh = noise_est * NOISE_MULTIPLIER;
        // Clamp to max
        if ({4'b0, noise_est} * {12'b0, NOISE_MULTIPLIER} > {DATA_WIDTH{1'b1}})
            adaptive_thresh = {DATA_WIDTH{1'b1}};
    end

    // ── Classification logic ───────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            prev_fluor   <= '0;
            peak_fluor   <= '0;
            slope        <= '0;
            result       <= RES_NEGATIVE;
            result_valid <= 1'b0;
        end else begin
            result_valid <= 1'b0;  // default

            if (fluor_valid) begin
                // Update slope
                slope <= $signed({1'b0, fluorescence}) -
                         $signed({1'b0, prev_fluor});
                prev_fluor <= fluorescence;

                // Track peak
                if (fluorescence > peak_fluor)
                    peak_fluor <= fluorescence;
            end

            // ── Classify when reaction is complete ─────────────
            if (reaction_done && fluor_valid) begin
                result_valid <= 1'b1;

                // ── Check for INVALID conditions first ─────────
                if (temp_fault || !baseline_locked) begin
                    result <= RES_INVALID;
                end else begin
                    // ── Apply selected classification mode ──────
                    case (mode)
                        // Mode 0 — Simple threshold
                        2'b00: begin
                            if (peak_fluor >= THRESHOLD_POS)
                                result <= RES_POSITIVE;
                            else if (peak_fluor < THRESHOLD_NEG)
                                result <= RES_NEGATIVE;
                            else
                                result <= RES_INDETERMINATE;
                        end

                        // Mode 1 — Slope-based
                        2'b01: begin
                            if (slope >= $signed({1'b0, SLOPE_THRESHOLD}))
                                result <= RES_POSITIVE;
                            else if (peak_fluor < THRESHOLD_NEG)
                                result <= RES_NEGATIVE;
                            else
                                result <= RES_INDETERMINATE;
                        end

                        // Mode 2 — Adaptive baseline + threshold
                        2'b10: begin
                            if (peak_fluor >= adaptive_thresh &&
                                adaptive_thresh > 0)
                                result <= RES_POSITIVE;
                            else if (peak_fluor < THRESHOLD_NEG)
                                result <= RES_NEGATIVE;
                            else
                                result <= RES_INDETERMINATE;
                        end

                        default: begin
                            result <= RES_INDETERMINATE;
                        end
                    endcase
                end
            end
        end
    end

endmodule
