// ============================================================================
// baseline_estimator.sv — Adaptive Baseline Subtraction
// ============================================================================
//
// Estimates the fluorescence baseline from early samples and provides
// baseline-corrected output for the decision engine.
//
// From Simulation Plan, Section 23 (Mode 3 — adaptive baseline):
//
//     baseline estimation → noise estimation → adaptive threshold
//
// Algorithm:
//     1. During the BASELINE phase (first N_BASELINE samples):
//        - Accumulate samples into a running sum
//        - Compute mean = sum / N_BASELINE
//        - Compute noise_est = max deviation from mean
//
//     2. After baseline is locked:
//        - corrected = sample − baseline_mean
//        - Output the corrected signal
//
// Parameters:
//     DATA_WIDTH     : Bit width of samples
//     BASELINE_LOG2  : log2(number of baseline samples), e.g. 4 → 16 samples
//
// Ports:
//     sample_in      : Raw filtered sample
//     sample_valid   : Pulse when sample is ready
//     corrected_out  : Baseline-corrected output
//     corrected_valid: Pulse when corrected output is ready
//     baseline_mean  : Computed baseline value (for status readout)
//     noise_est      : Estimated noise floor (for adaptive threshold)
//     baseline_locked: High once baseline computation is complete
// ============================================================================

module baseline_estimator #(
    parameter DATA_WIDTH    = 12,
    parameter BASELINE_LOG2 = 4     // 2^4 = 16 baseline samples
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // Input
    input  logic [DATA_WIDTH-1:0]   sample_in,
    input  logic                    sample_valid,

    // Corrected output
    output logic [DATA_WIDTH-1:0]   corrected_out,
    output logic                    corrected_valid,

    // Baseline info
    output logic [DATA_WIDTH-1:0]   baseline_mean,
    output logic [DATA_WIDTH-1:0]   noise_est,
    output logic                    baseline_locked
);

    // ── Derived constants ──────────────────────────────────────────────
    localparam N_BASELINE = 1 << BASELINE_LOG2;
    localparam ACC_WIDTH  = DATA_WIDTH + BASELINE_LOG2;

    // ── Baseline accumulation ──────────────────────────────────────────
    logic [ACC_WIDTH-1:0]    bl_sum;
    logic [BASELINE_LOG2:0]  bl_count;
    logic [DATA_WIDTH-1:0]   bl_mean_reg;
    logic [DATA_WIDTH-1:0]   bl_max;
    logic [DATA_WIDTH-1:0]   bl_min;
    logic                    locked;

    assign baseline_locked = locked;
    assign baseline_mean   = bl_mean_reg;

    // ── Main logic ─────────────────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            bl_sum         <= '0;
            bl_count       <= '0;
            bl_mean_reg    <= '0;
            bl_max         <= '0;
            bl_min         <= {DATA_WIDTH{1'b1}};  // max unsigned
            noise_est      <= '0;
            locked         <= 1'b0;
            corrected_out  <= '0;
            corrected_valid <= 1'b0;
        end else begin
            corrected_valid <= 1'b0;  // default

            if (sample_valid) begin
                if (!locked) begin
                    // ── Accumulating baseline samples ──────────────
                    bl_sum   <= bl_sum + {1'b0, sample_in};
                    bl_count <= bl_count + 1'b1;

                    // Track min/max for noise estimation
                    if (sample_in > bl_max)
                        bl_max <= sample_in;
                    if (sample_in < bl_min)
                        bl_min <= sample_in;

                    // Check if we have enough samples
                    if (bl_count == N_BASELINE - 1) begin
                        // Compute mean via right-shift
                        bl_mean_reg <= (bl_sum + {1'b0, sample_in})
                                       >> BASELINE_LOG2;

                        // Noise estimate = (max − min) / 2
                        // Approximate: just use (max − min) as peak-to-peak
                        if (bl_max >= bl_min)
                            noise_est <= (bl_max - bl_min);
                        else
                            noise_est <= '0;

                        locked <= 1'b1;
                    end

                end else begin
                    // ── Baseline locked: output corrected signal ───
                    if (sample_in >= bl_mean_reg)
                        corrected_out <= sample_in - bl_mean_reg;
                    else
                        corrected_out <= '0;  // clamp at zero

                    corrected_valid <= 1'b1;
                end
            end
        end
    end

endmodule
