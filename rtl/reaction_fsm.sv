// ============================================================================
// reaction_fsm.sv — Master Reaction Sequencer FSM
// ============================================================================
//
// Controls the complete diagnostic procedure from sample insertion
// to final result (Simulation Plan, Section 11):
//
//     IDLE → CARTRIDGE_CHECK → PREHEAT → LAMP → TRANSFER →
//     CRISPR → READ → ANALYZE → RESULT
//
// Each state has a configurable timeout. The FSM coordinates:
//     - thermal_controller (setpoint changes)
//     - optical_acquisition (measurement triggers)
//     - decision_engine (final classification trigger)
//
// The FSM also handles error/fault conditions:
//     - Temperature fault → FAULT state → INVALID result
//     - Timeout exceeded → FAULT state
//     - User abort → IDLE
//
// Parameters:
//     CLK_FREQ_HZ     : System clock frequency (for timer calculations)
//     PREHEAT_MS       : Preheat duration (milliseconds)
//     LAMP_MS          : LAMP reaction duration (milliseconds)
//     TRANSFER_MS      : Fluid transfer settling time (ms)
//     CRISPR_MS        : CRISPR incubation duration (ms)
//     READ_INTERVAL_MS : Optical read interval during CRISPR (ms)
//     LAMP_TEMP_CODE   : ADC code for LAMP temperature setpoint
//     CRISPR_TEMP_CODE : ADC code for CRISPR temperature setpoint
//
// Outputs:
//     state_out        : Current FSM state (for status register / debug)
//     temp_setpoint    : Temperature setpoint passed to thermal controller
//     optical_trigger  : Pulse to trigger optical measurement
//     reaction_done    : Asserted when entering ANALYZE/RESULT
//     result_code      : Final 2-bit result from decision engine
//     result_ready     : Asserted when result is available
//     fault            : Fault indicator
// ============================================================================

module reaction_fsm #(
    parameter CLK_FREQ_HZ     = 50_000_000,   // 50 MHz
    parameter PREHEAT_MS      = 30_000,        // 30 s preheat
    parameter LAMP_MS         = 1_800_000,     // 30 min = 1,800,000 ms
    parameter TRANSFER_MS     = 5_000,         // 5 s transfer
    parameter CRISPR_MS       = 900_000,       // 15 min = 900,000 ms
    parameter READ_INTERVAL_MS= 10_000,        // read every 10 s during CRISPR
    parameter DATA_WIDTH      = 12,
    parameter LAMP_TEMP_CODE  = 12'd2583,      // ~63 °C mapped to 12-bit ADC
    parameter CRISPR_TEMP_CODE= 12'd1516       // ~37 °C mapped to 12-bit ADC
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // User control
    input  logic                    start,          // begin assay
    input  logic                    abort,          // user abort

    // Cartridge detection
    input  logic                    cartridge_in,   // cartridge inserted

    // Temperature interface (to/from thermal_controller)
    input  logic                    temp_valid,     // temp within tolerance
    input  logic                    temp_fault,     // temperature fault
    output logic [DATA_WIDTH-1:0]   temp_setpoint,  // setpoint to controller

    // Optical interface (to/from optical_acquisition)
    output logic                    optical_trigger, // trigger measurement
    input  logic                    optical_done,    // measurement complete

    // Decision engine interface
    output logic                    reaction_done,   // reaction timer done
    input  logic [1:0]              decision_result, // from decision_engine
    input  logic                    decision_valid,  // result available

    // Outputs
    output logic [3:0]              state_out,       // current state code
    output logic [1:0]              result_code,     // final result
    output logic                    result_ready,    // result available
    output logic                    fault            // fault indicator
);

    // ── FSM states ─────────────────────────────────────────────────────
    typedef enum logic [3:0] {
        ST_IDLE            = 4'd0,
        ST_CARTRIDGE_CHECK = 4'd1,
        ST_PREHEAT         = 4'd2,
        ST_LAMP            = 4'd3,
        ST_TRANSFER        = 4'd4,
        ST_CRISPR          = 4'd5,
        ST_READ            = 4'd6,
        ST_ANALYZE         = 4'd7,
        ST_RESULT          = 4'd8,
        ST_FAULT           = 4'd9
    } fsm_state_t;

    fsm_state_t state;

    assign state_out = state;

    // ── Timer ──────────────────────────────────────────────────────────
    // Counts clock cycles. Duration parameters are in ms.
    // cycles_per_ms = CLK_FREQ_HZ / 1000
    localparam CYCLES_PER_MS = CLK_FREQ_HZ / 1000;

    logic [47:0] timer;              // 48-bit: supports up to ~78 hours at 1 GHz
    logic [47:0] timer_target;

    // Read interval timer (for periodic optical reads during CRISPR)
    logic [47:0] read_timer;
    logic [47:0] read_target;

    // ── Optical read count ─────────────────────────────────────────────
    logic [7:0] read_count;

    // ── Main FSM ───────────────────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state           <= ST_IDLE;
            timer           <= '0;
            read_timer      <= '0;
            read_count      <= '0;
            temp_setpoint   <= '0;
            optical_trigger <= 1'b0;
            reaction_done   <= 1'b0;
            result_code     <= 2'b00;
            result_ready    <= 1'b0;
            fault           <= 1'b0;
        end else begin
            // Defaults
            optical_trigger <= 1'b0;
            result_ready    <= 1'b0;

            // Global abort
            if (abort && state != ST_IDLE) begin
                state <= ST_IDLE;
                fault <= 1'b0;
                reaction_done <= 1'b0;
            end

            // Global fault check (except in IDLE, RESULT, FAULT)
            if (temp_fault && state != ST_IDLE &&
                state != ST_RESULT && state != ST_FAULT &&
                state != ST_CARTRIDGE_CHECK) begin
                state <= ST_FAULT;
                fault <= 1'b1;
            end

            case (state)
                // ─── IDLE ─────────────────────────────────────────
                ST_IDLE: begin
                    fault         <= 1'b0;
                    reaction_done <= 1'b0;
                    result_ready  <= 1'b0;
                    temp_setpoint <= '0;
                    if (start) begin
                        state <= ST_CARTRIDGE_CHECK;
                        timer <= '0;
                    end
                end

                // ─── CARTRIDGE CHECK ──────────────────────────────
                ST_CARTRIDGE_CHECK: begin
                    if (cartridge_in) begin
                        state         <= ST_PREHEAT;
                        temp_setpoint <= LAMP_TEMP_CODE;
                        timer         <= '0;
                        timer_target  <= PREHEAT_MS * CYCLES_PER_MS;
                    end
                    // Timeout after 30 seconds
                    else if (timer >= 30_000 * CYCLES_PER_MS) begin
                        state <= ST_FAULT;
                        fault <= 1'b1;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end

                // ─── PREHEAT ──────────────────────────────────────
                ST_PREHEAT: begin
                    temp_setpoint <= LAMP_TEMP_CODE;
                    timer <= timer + 1'b1;

                    // Wait for temperature to stabilise AND minimum time
                    if (temp_valid && timer >= timer_target) begin
                        state        <= ST_LAMP;
                        timer        <= '0;
                        timer_target <= LAMP_MS * CYCLES_PER_MS;
                    end
                end

                // ─── LAMP AMPLIFICATION ───────────────────────────
                ST_LAMP: begin
                    temp_setpoint <= LAMP_TEMP_CODE;
                    timer <= timer + 1'b1;

                    if (timer >= timer_target) begin
                        state         <= ST_TRANSFER;
                        timer         <= '0;
                        timer_target  <= TRANSFER_MS * CYCLES_PER_MS;
                    end
                end

                // ─── FLUID TRANSFER ───────────────────────────────
                ST_TRANSFER: begin
                    // Ramp temperature down to CRISPR temp
                    temp_setpoint <= CRISPR_TEMP_CODE;
                    timer <= timer + 1'b1;

                    if (timer >= timer_target) begin
                        state        <= ST_CRISPR;
                        timer        <= '0;
                        timer_target <= CRISPR_MS * CYCLES_PER_MS;
                        read_timer   <= '0;
                        read_target  <= READ_INTERVAL_MS * CYCLES_PER_MS;
                        read_count   <= '0;
                    end
                end

                // ─── CRISPR INCUBATION ────────────────────────────
                ST_CRISPR: begin
                    temp_setpoint <= CRISPR_TEMP_CODE;
                    timer      <= timer + 1'b1;
                    read_timer <= read_timer + 1'b1;

                    // Periodic optical reads
                    if (read_timer >= read_target) begin
                        optical_trigger <= 1'b1;
                        read_timer      <= '0;
                        state           <= ST_READ;
                    end

                    // CRISPR timer done → go to analyze
                    if (timer >= timer_target) begin
                        state         <= ST_ANALYZE;
                        reaction_done <= 1'b1;
                        // Trigger one final read
                        optical_trigger <= 1'b1;
                    end
                end

                // ─── OPTICAL READ (during CRISPR) ─────────────────
                ST_READ: begin
                    temp_setpoint <= CRISPR_TEMP_CODE;
                    timer <= timer + 1'b1;

                    if (optical_done) begin
                        read_count <= read_count + 1'b1;
                        state      <= ST_CRISPR;
                    end
                end

                // ─── ANALYZE ──────────────────────────────────────
                ST_ANALYZE: begin
                    reaction_done <= 1'b1;

                    if (decision_valid) begin
                        result_code  <= decision_result;
                        result_ready <= 1'b1;
                        state        <= ST_RESULT;
                    end
                end

                // ─── RESULT ───────────────────────────────────────
                ST_RESULT: begin
                    result_ready  <= 1'b1;
                    reaction_done <= 1'b0;
                    temp_setpoint <= '0;  // cool down

                    // Stay in RESULT until user starts a new test
                    if (start) begin
                        state <= ST_IDLE;
                    end
                end

                // ─── FAULT ────────────────────────────────────────
                ST_FAULT: begin
                    fault         <= 1'b1;
                    result_code   <= 2'b11;  // INVALID
                    result_ready  <= 1'b1;
                    temp_setpoint <= '0;     // kill heater

                    if (start) begin
                        state <= ST_IDLE;
                        fault <= 1'b0;
                    end
                end

                default: state <= ST_IDLE;
            endcase
        end
    end

endmodule
