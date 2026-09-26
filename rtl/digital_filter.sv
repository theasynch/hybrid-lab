// ============================================================================
// digital_filter.sv — Moving-Average Digital Filter
// ============================================================================
//
// Implements the noise-rejection stage of the signal processing pipeline
// (Simulation Plan, Section 11):
//
//     Y[n] = (1/N) * Σ(k=0 to N-1) X[n-k]
//
// Uses an efficient sliding-window approach:
//     accumulator += new_sample - oldest_sample
//     average = accumulator >> log2(N)      (for power-of-2 windows)
//
// For non-power-of-2 windows, a proper divider would be required.
// We restrict N to powers of 2 for hardware simplicity.
//
// Parameters:
//     DATA_WIDTH  : Bit width of input/output samples (default 12)
//     WINDOW_LOG2 : log2(window size), e.g. 3 → window of 8 samples
//
// Ports:
//     clk         : System clock
//     rst_n       : Active-low synchronous reset
//     sample_valid: Pulse high for one clock when a new sample is ready
//     sample_in   : New ADC sample (unsigned)
//     avg_out     : Filtered output (unsigned)
//     avg_valid   : Pulses high when a new filtered value is ready
// ============================================================================

module digital_filter #(
    parameter DATA_WIDTH  = 12,
    parameter WINDOW_LOG2 = 3    // window size = 2^3 = 8 samples
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // Sample input
    input  logic                    sample_valid,
    input  logic [DATA_WIDTH-1:0]   sample_in,

    // Filtered output
    output logic [DATA_WIDTH-1:0]   avg_out,
    output logic                    avg_valid
);

    // ── Derived constants ──────────────────────────────────────────────
    localparam WINDOW_SIZE = 1 << WINDOW_LOG2;
    localparam ACC_WIDTH   = DATA_WIDTH + WINDOW_LOG2;  // prevent overflow

    // ── Shift register (circular buffer) ───────────────────────────────
    logic [DATA_WIDTH-1:0] buffer [0:WINDOW_SIZE-1];
    logic [WINDOW_LOG2-1:0] wr_ptr;

    // ── Running accumulator ────────────────────────────────────────────
    logic [ACC_WIDTH-1:0] accumulator;

    // ── Sample count (tracks how many samples have been loaded) ────────
    logic [WINDOW_LOG2:0] sample_count;
    logic window_full;

    assign window_full = sample_count >= WINDOW_SIZE;

    // ── Main logic ─────────────────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            wr_ptr      <= '0;
            accumulator <= '0;
            sample_count <= '0;
            avg_valid   <= 1'b0;

            for (int i = 0; i < WINDOW_SIZE; i++)
                buffer[i] <= '0;

        end else begin
            avg_valid <= 1'b0;  // default: no output this cycle

            if (sample_valid) begin
                // Subtract the oldest sample from the accumulator
                accumulator <= accumulator
                             + {1'b0, sample_in}
                             - {1'b0, buffer[wr_ptr]};

                // Store new sample
                buffer[wr_ptr] <= sample_in;

                // Advance write pointer
                wr_ptr <= wr_ptr + 1'b1;

                // Track sample count
                if (!window_full)
                    sample_count <= sample_count + 1'b1;

                // Output is valid after the first full window
                avg_valid <= window_full || (sample_count == WINDOW_SIZE - 1);
            end
        end
    end

    // ── Output: divide by N via right-shift ────────────────────────────
    assign avg_out = accumulator[ACC_WIDTH-1 : WINDOW_LOG2];

endmodule
