--------------------------------------------------------------------------------
-- scan_core
--------------------------------------------------------------------------------
-- The scan chain shift register and phase controller.
--
-- Deliberately contains NO vendor primitives. Everything Xilinx-specific lives
-- in TopLevel.vhd, which instantiates BSCANE2 and wires it to this entity. That
-- separation is what allows scan_core to be simulated with a plain VHDL
-- simulator, with no unisim library and no BSCANE2 model -- a testbench simply
-- drives the capture/shift/update ports itself.
--
-- Protocol
-- --------
-- One test vector is two DR scans, distinguished by the `io` phase bit:
--
--   io = '0'  input phase   shifting fills `data`;
--                           Update-DR latches `data` into dut_input.
--   io = '1'  output phase  Capture-DR samples dut_output into `datau`;
--                           shifting streams it out on tdo.
--
-- `io` inverts on every Update-DR, so host and FPGA alternate in lockstep.
--
-- Bit order: the register shifts LSB-first (new bits enter at the MSB end and
-- exit at bit 0), matching the host driver, which shifts the tracefile's MSB
-- last. See docs/TRACEFILE_FORMAT.md.
--
-- Original implementation by Anubhav Bhura, Wadhwani Electronics Laboratory,
-- IIT Bombay. This entity is that logic extracted unchanged, plus the two
-- fixes noted below.
--
-- Fixes relative to the original (see docs/KNOWN_ISSUES.md):
--
--   #1  `io` now has a reset path. Previously it was initialised only at FPGA
--       configuration, so a host script that died mid-vector left the FPGA's
--       phase permanently inverted with no recovery short of reprogramming.
--       It is now cleared asynchronously in Test-Logic-Reset (jtag_reset) and
--       synchronously whenever this data register is deselected (sel = '0').
--       The host already issues a TAP reset before every run, so each run now
--       self-synchronises.
--
--   #2  tdo is now registered on the FALLING edge of tck rather than driven
--       combinationally from a rising-edge register. IEEE 1149.1 requires TDO
--       to change on the falling edge so the host can sample it safely on the
--       rising edge. The bit sequence on the wire is unchanged -- see the
--       timing note below -- so no host-side change is required.
--
-- Falling-edge TDO timing, for reference:
--
--   rising  N     Capture-DR: datau <= dut_output       (datau(0) = d0)
--   falling N     tdo <= datau(0) = d0
--   rising  N+1   host samples tdo = d0  [stable, launched half a cycle ago]
--                 datau shifts           (datau(0) = d1)
--   falling N+1   tdo <= d1
--   rising  N+2   host samples tdo = d1
--
-- Same data, same order, no added latency -- only the launch edge moves.
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity scan_core is
  generic (
    number_of_inputs  : integer := 7;
    number_of_outputs : integer := 1
  );
  port (
    -- JTAG side (driven by BSCANE2 in TopLevel, or by a testbench in sim)
    tck        : in  std_logic;
    tdi        : in  std_logic;
    tdo        : out std_logic;
    capture    : in  std_logic;   -- high in Capture-DR
    shift      : in  std_logic;   -- high in Shift-DR
    update     : in  std_logic;   -- one-cycle pulse in Update-DR
    jtag_reset : in  std_logic;   -- high in Test-Logic-Reset
    sel        : in  std_logic;   -- high while this DR is selected (USER1)

    -- DUT side
    dut_input  : out std_logic_vector(number_of_inputs-1 downto 0);
    dut_output : in  std_logic_vector(number_of_outputs-1 downto 0);

    -- Observability. Exposed for a logic analyser or a testbench assertion;
    -- TopLevel leaves it unconnected so it costs nothing when unused.
    io_phase   : out std_logic
  );
end entity scan_core;

architecture rtl of scan_core is

  signal data  : std_logic_vector(number_of_inputs-1 downto 0)  := (others => '0');
  signal datau : std_logic_vector(number_of_outputs-1 downto 0) := (others => '0');
  signal din   : std_logic_vector(number_of_inputs-1 downto 0)  := (others => '0');

  signal io : std_logic := '0';  -- '0' = input phase, '1' = output phase

begin

  ------------------------------------------------------------------------------
  -- Shift register and phase control
  --
  -- The if/elsif chain is safe: Update-DR, Capture-DR and Shift-DR are mutually
  -- exclusive TAP states, so at most one branch is ever eligible in a cycle and
  -- the priority ordering between them is irrelevant.
  ------------------------------------------------------------------------------
  shift_reg : process(tck, jtag_reset)
  begin
    if jtag_reset = '1' then
      -- FIX #1: Test-Logic-Reset clears the phase asynchronously, so recovery
      -- does not depend on tck still being clocked.
      io <= '0';

    elsif rising_edge(tck) then

      if sel = '0' then
        -- FIX #1: this data register is not selected (the TAP is running some
        -- other instruction). Park the phase at input so the next run starts
        -- from a known state.
        io <= '0';

      elsif update = '1' then          -- Update-DR
        io <= not io;
        if io = '0' then
          din <= data;                 -- present the new input vector to the DUT
        end if;

      elsif capture = '1' then         -- Capture-DR
        if io = '1' then
          datau <= dut_output;         -- sample the DUT response
        end if;

      elsif shift = '1' then           -- Shift-DR
        if io = '0' then
          -- input phase: shift the incoming vector in, LSB-first
          if number_of_inputs = 1 then
            data(0) <= tdi;
          else
            data <= tdi & data(number_of_inputs-1 downto 1);
          end if;
        else
          -- output phase: shift the captured response out, LSB-first
          if number_of_outputs = 1 then
            datau(0) <= '0';
          else
            datau <= '0' & datau(number_of_outputs-1 downto 1);
          end if;
        end if;

      end if;
    end if;
  end process shift_reg;

  ------------------------------------------------------------------------------
  -- FIX #2: TDO launched on the falling edge of tck, per IEEE 1149.1, so the
  -- host's rising-edge sample lands half a tck period after the launch instead
  -- of on the same edge.
  ------------------------------------------------------------------------------
  tdo_reg : process(tck)
  begin
    if falling_edge(tck) then
      tdo <= datau(0);
    end if;
  end process tdo_reg;

  dut_input <= din;
  io_phase  <= io;

end architecture rtl;
