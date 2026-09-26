// ============================================================================
// optical_acquisition.sv — LED-Modulated Optical ADC Interface
// ============================================================================
//
// Implements the LED on/off differential measurement from the
// Simulation Plan, Section 11:
//
//     LED ON  → ADC → V_on
//     LED OFF → ADC → V_off
//     S = V_on − V_off         (ambient-light cancellation)
//
// Sequencing:
//     1. Assert led_en HIGH, wait settle_cycles
//     2. Trigger ADC conversion (adc_start), capture V_on
//     3. De-assert led_en LOW, wait settle_cycles
//     4. Trigger ADC conversion, capture V_off
//     5. Compute differential: S = V_on − V_off
//     6. Assert result_valid with the differential value
//
// The module runs autonomously once triggered by 'start'.
// It produces one differential sample per measurement cycle.
//
// Parameters:
//     DATA_WIDTH     : ADC data width (bits)
//     SETTLE_CYCLES  : LED on/off settling time (clock cycles)
//
// Ports:
//     clk, rst_n     : Clock and reset
//     start          : Begin a measurement cycle
//     adc_data       : ADC data input (from external ADC model or pin)
//     adc_valid      : ADC conversion complete
//     adc_start      : ADC conversion trigger (active high pulse)
//     led_en         : LED drive enable
//     diff_out       : Differential result S = V_on − V_off
//     diff_valid     : Pulsed when diff_out is valid
//     busy           : High while measurement is in progress
// ============================================================================

module optical_acquisition #(
    parameter DATA_WIDTH    = 12,
    parameter SETTLE_CYCLES = 100    // LED settle time in clk cycles
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // Control
    input  logic                    start,
    output logic                    busy,

    // ADC interface
    input  logic [DATA_WIDTH-1:0]   adc_data,
    input  logic                    adc_valid,
    output logic                    adc_start,

    // LED control
    output logic                    led_en,

    // Differential output
    output logic [DATA_WIDTH-1:0]   diff_out,
    output logic                    diff_valid
);

    // ── FSM states ─────────────────────────────────────────────────────
    typedef enum logic [2:0] {
        S_IDLE,
        S_LED_ON_SETTLE,
        S_ADC_ON,
        S_WAIT_ON,
        S_LED_OFF_SETTLE,
        S_ADC_OFF,
        S_WAIT_OFF,
        S_COMPUTE
    } state_t;

    state_t state, state_next;

    // ── Internal registers ─────────────────────────────────────────────
    logic [15:0]           settle_cnt;
    logic [DATA_WIDTH-1:0] v_on;
    logic [DATA_WIDTH-1:0] v_off;

    // ── FSM ────────────────────────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state      <= S_IDLE;
            settle_cnt <= '0;
            v_on       <= '0;
            v_off      <= '0;
            diff_out   <= '0;
            diff_valid <= 1'b0;
            adc_start  <= 1'b0;
            led_en     <= 1'b0;
            busy       <= 1'b0;
        end else begin
            // Defaults
            diff_valid <= 1'b0;
            adc_start  <= 1'b0;

            case (state)
                // ─── IDLE ─────────────────────────────────────────
                S_IDLE: begin
                    busy   <= 1'b0;
                    led_en <= 1'b0;
                    if (start) begin
                        state  <= S_LED_ON_SETTLE;
                        led_en <= 1'b1;
                        settle_cnt <= '0;
                        busy   <= 1'b1;
                    end
                end

                // ─── LED ON — wait for settle ─────────────────────
                S_LED_ON_SETTLE: begin
                    led_en <= 1'b1;
                    if (settle_cnt >= SETTLE_CYCLES - 1) begin
                        state     <= S_ADC_ON;
                        adc_start <= 1'b1;
                    end else begin
                        settle_cnt <= settle_cnt + 1'b1;
                    end
                end

                // ─── Trigger ADC (LED on) ─────────────────────────
                S_ADC_ON: begin
                    led_en <= 1'b1;
                    state  <= S_WAIT_ON;
                end

                // ─── Wait for ADC result (LED on) ─────────────────
                S_WAIT_ON: begin
                    led_en <= 1'b1;
                    if (adc_valid) begin
                        v_on       <= adc_data;
                        led_en     <= 1'b0;       // turn off LED
                        settle_cnt <= '0;
                        state      <= S_LED_OFF_SETTLE;
                    end
                end

                // ─── LED OFF — wait for settle ────────────────────
                S_LED_OFF_SETTLE: begin
                    led_en <= 1'b0;
                    if (settle_cnt >= SETTLE_CYCLES - 1) begin
                        state     <= S_ADC_OFF;
                        adc_start <= 1'b1;
                    end else begin
                        settle_cnt <= settle_cnt + 1'b1;
                    end
                end

                // ─── Trigger ADC (LED off) ────────────────────────
                S_ADC_OFF: begin
                    state <= S_WAIT_OFF;
                end

                // ─── Wait for ADC result (LED off) ────────────────
                S_WAIT_OFF: begin
                    if (adc_valid) begin
                        v_off <= adc_data;
                        state <= S_COMPUTE;
                    end
                end

                // ─── Compute differential ─────────────────────────
                S_COMPUTE: begin
                    // Saturating subtraction: if v_on < v_off, clamp to 0
                    if (v_on >= v_off)
                        diff_out <= v_on - v_off;
                    else
                        diff_out <= '0;

                    diff_valid <= 1'b1;
                    state      <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
