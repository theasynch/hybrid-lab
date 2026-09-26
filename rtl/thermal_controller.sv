// ============================================================================
// thermal_controller.sv — PID Temperature Controller (Digital)
// ============================================================================
//
// Digital PID controller for the reaction chamber heater
// (Simulation Plan, Section 11):
//
//     error = T_target − T_actual
//     u(t) = Kp·e(t) + Ki·∫e(τ)dτ + Kd·de/dt
//
// Implementation notes:
//     - Fixed-point arithmetic (Q8.8 for gains, Q16.0 for accumulator)
//     - Anti-windup: integral clamped to ±WINDUP_LIMIT
//     - Output clamped to [0, PWM_MAX] (no negative heating)
//     - Derivative computed as first-order difference
//     - All gains are compile-time configurable via parameters
//
// Inputs:
//     temp_adc    : Temperature sensor ADC reading (unsigned)
//     setpoint    : Target temperature ADC code (unsigned)
//     update      : Pulse to trigger one PID update
//
// Outputs:
//     heater_pwm  : PWM duty cycle value for heater drive
//     temp_valid  : Temperature is within ±TOLERANCE of setpoint
//     temp_fault  : Temperature out of safe range
// ============================================================================

module thermal_controller #(
    parameter DATA_WIDTH   = 12,
    parameter PWM_WIDTH    = 10,       // 10-bit PWM → 1024 levels
    parameter KP           = 16'd80,   // proportional gain (Q8.8 → 0.3125)
    parameter KI           = 16'd4,    // integral gain     (Q8.8 → 0.015625)
    parameter KD           = 16'd16,   // derivative gain   (Q8.8 → 0.0625)
    parameter WINDUP_LIMIT = 32'd100000, // anti-windup clamp
    parameter TOLERANCE    = 12'd10,   // ±10 ADC codes ≈ ±0.8 °C
    parameter TEMP_MIN     = 12'd200,  // minimum safe ADC code (~16 °C)
    parameter TEMP_MAX     = 12'd3500  // maximum safe ADC code (~85 °C)
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // Temperature input
    input  logic [DATA_WIDTH-1:0]   temp_adc,
    input  logic [DATA_WIDTH-1:0]   setpoint,
    input  logic                    update,      // pulse to update PID

    // Heater output
    output logic [PWM_WIDTH-1:0]    heater_pwm,

    // Status
    output logic                    temp_valid,  // within tolerance
    output logic                    temp_fault   // out of safe range
);

    // ── Fixed-point arithmetic ─────────────────────────────────────────
    // Using signed 32-bit for intermediate calculations
    logic signed [31:0] error;
    logic signed [31:0] error_prev;
    logic signed [31:0] integral;
    logic signed [31:0] derivative;
    logic signed [31:0] p_term;
    logic signed [31:0] i_term;
    logic signed [31:0] d_term;
    logic signed [31:0] pid_output;

    // ── Signed versions of inputs ──────────────────────────────────────
    logic signed [31:0] setpoint_s;
    logic signed [31:0] temp_s;

    assign setpoint_s = {20'b0, setpoint};
    assign temp_s     = {20'b0, temp_adc};

    // ── Tolerance check ────────────────────────────────────────────────
    logic signed [31:0] abs_error;
    assign abs_error  = (error >= 0) ? error : -error;
    assign temp_valid = (abs_error <= $signed({20'b0, TOLERANCE}));

    // ── Fault detection ────────────────────────────────────────────────
    // Only assert fault after at least one valid temperature reading
    logic has_valid_reading;
    assign temp_fault = has_valid_reading &&
                        ((temp_adc < TEMP_MIN) || (temp_adc > TEMP_MAX));

    // ── PID computation ────────────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            error             <= '0;
            error_prev        <= '0;
            integral          <= '0;
            derivative        <= '0;
            heater_pwm        <= '0;
            has_valid_reading <= 1'b0;
        end else if (update) begin
            has_valid_reading <= 1'b1;
            // Error
            error <= setpoint_s - temp_s;

            // Integral with anti-windup
            integral <= integral + error;
            if (integral + error > $signed(WINDUP_LIMIT))
                integral <= $signed(WINDUP_LIMIT);
            else if (integral + error < -$signed(WINDUP_LIMIT))
                integral <= -$signed(WINDUP_LIMIT);

            // Derivative (first-order difference)
            derivative <= error - error_prev;
            error_prev <= error;

            // PID terms (Q8.8 multiply then shift back)
            p_term = ($signed(KP) * error) >>> 8;
            i_term = ($signed(KI) * integral) >>> 8;
            d_term = ($signed(KD) * derivative) >>> 8;

            pid_output = p_term + i_term + d_term;

            // Output clamping: [0, PWM_MAX]
            if (pid_output < 0)
                heater_pwm <= '0;
            else if (pid_output > ((1 << PWM_WIDTH) - 1))
                heater_pwm <= {PWM_WIDTH{1'b1}};  // saturate to max
            else
                heater_pwm <= pid_output[PWM_WIDTH-1:0];
        end
    end

endmodule
