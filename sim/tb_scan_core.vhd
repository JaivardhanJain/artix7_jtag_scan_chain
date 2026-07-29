--------------------------------------------------------------------------------
-- tb_scan_core
--------------------------------------------------------------------------------
-- Self-checking testbench for hdl/scan_core.vhd.
--
-- This exists because scan_core has no vendor primitives: it can be simulated
-- with any VHDL simulator, no unisim and no BSCANE2 model. The testbench plays
-- the role BSCANE2 plays on hardware -- it drives capture/shift/update/tck and
-- reads tdo -- and it samples tdo on the RISING edge of tck, exactly as the
-- host's MPSSE 0x2C/0x2E reads do. So a timing mistake that would show up on
-- the bench shows up here too.
--
-- The DUT is modelled inline as a combinational function, and the expected
-- result is computed with the same function. No tracefile is needed: the
-- testbench is its own golden model.
--
-- Tests
-- -----
--   1  Exhaustive scan       every input vector shifted in, result shifted out
--                            and compared. Covers shift ordering, phase
--                            alternation, capture timing and the falling-edge
--                            TDO launch (KNOWN_ISSUES #2).
--   2  Desync recovery       abandon a vector halfway, pulse jtag_reset, then
--                            run a normal vector. Fails on the ORIGINAL code,
--                            passes with the reset path (KNOWN_ISSUES #1).
--   3  Deselect recovery     same, but recovering via sel = '0' instead.
--   4  Bit-order sensitivity  a deliberately reversed vector must NOT match.
--                            Guards against a testbench that passes anything.
--
-- Run:  sim/run_sim.bat        (Vivado xsim)
--       ghdl -a/-e/-r          (see sim/README.md)
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_scan_core is
  generic (
    NUM_IN  : integer := 8;
    NUM_OUT : integer := 4
  );
end entity tb_scan_core;

architecture sim of tb_scan_core is

  constant HALF : time := 10 ns;   -- half a tck period

  component scan_core is
    generic (
      number_of_inputs  : integer;
      number_of_outputs : integer
    );
    port (
      tck        : in  std_logic;
      tdi        : in  std_logic;
      tdo        : out std_logic;
      capture    : in  std_logic;
      shift      : in  std_logic;
      update     : in  std_logic;
      jtag_reset : in  std_logic;
      sel        : in  std_logic;
      dut_input  : out std_logic_vector(number_of_inputs-1 downto 0);
      dut_output : in  std_logic_vector(number_of_outputs-1 downto 0);
      io_phase   : out std_logic
    );
  end component;

  signal tck        : std_logic := '0';
  signal tdi        : std_logic := '0';
  signal tdo        : std_logic;
  signal capture    : std_logic := '0';
  signal shift      : std_logic := '0';
  signal update     : std_logic := '0';
  signal jtag_reset : std_logic := '0';
  signal sel        : std_logic := '1';

  signal dut_input  : std_logic_vector(NUM_IN-1 downto 0);
  signal dut_output : std_logic_vector(NUM_OUT-1 downto 0);
  signal io_phase   : std_logic;

  -- Written by the scan_out procedure. Declared at architecture level because
  -- a procedure returns through a signal parameter, which must resolve to a
  -- signal visible outside the procedure.
  signal result_sig : std_logic_vector(NUM_OUT-1 downto 0) := (others => '0');

  signal errors : integer := 0;
  signal checks : integer := 0;

  ------------------------------------------------------------------------------
  -- Golden model. Any function of the input will do; this one mixes both
  -- halves of the input so a swapped or reversed vector cannot coincidentally
  -- produce the right answer.
  ------------------------------------------------------------------------------
  function dut_model (v : std_logic_vector(NUM_IN-1 downto 0))
    return std_logic_vector is
  begin
    return v(NUM_OUT-1 downto 0) xor v(NUM_IN-1 downto NUM_IN-NUM_OUT);
  end function dut_model;

  function to_str (v : std_logic_vector) return string is
    variable s : string(1 to v'length);
    variable i : integer := 1;
  begin
    for k in v'high downto v'low loop
      if v(k) = '1' then s(i) := '1'; else s(i) := '0'; end if;
      i := i + 1;
    end loop;
    return s;
  end function to_str;

begin

  ------------------------------------------------------------------------------
  -- The "DUT": purely combinational, mirroring the golden model
  ------------------------------------------------------------------------------
  dut_output <= dut_model(dut_input);

  uut : scan_core
    generic map (
      number_of_inputs  => NUM_IN,
      number_of_outputs => NUM_OUT
    )
    port map (
      tck        => tck,
      tdi        => tdi,
      tdo        => tdo,
      capture    => capture,
      shift      => shift,
      update     => update,
      jtag_reset => jtag_reset,
      sel        => sel,
      dut_input  => dut_input,
      dut_output => dut_output,
      io_phase   => io_phase
    );

  ------------------------------------------------------------------------------
  -- Stimulus
  ------------------------------------------------------------------------------
  stim : process

    -- One tck period. Control signals are set while tck is low, so they are
    -- stable before the rising edge -- same discipline the TAP controller uses.
    procedure tick is
    begin
      wait for 0 ns;    -- let control-signal assignments settle before the edge
      tck <= '1';
      wait for HALF;
      tck <= '0';
      wait for HALF;
    end procedure tick;

    -- Test-Logic-Reset. Asynchronous in scan_core, so no tck is required --
    -- which is the point: recovery must not depend on a clock still running.
    procedure tap_reset is
    begin
      jtag_reset <= '1';
      wait for HALF;
      jtag_reset <= '0';
      wait for HALF;
    end procedure tap_reset;

    -- Input phase: Capture-DR, NUM_IN Shift-DR cycles, Update-DR.
    -- Bits go in LSB-first: scan_core shifts new bits in at the MSB end and
    -- toward bit 0, so the first bit sent lands in bit 0. The host driver
    -- achieves the same by sending the tracefile's MSB last.
    procedure scan_in (v : std_logic_vector(NUM_IN-1 downto 0);
                       reversed : boolean := false) is
    begin
      capture <= '1'; tick; capture <= '0';
      shift <= '1';
      for i in 0 to NUM_IN-1 loop
        if reversed then
          tdi <= v(NUM_IN-1-i);
        else
          tdi <= v(i);
        end if;
        tick;
      end loop;
      shift <= '0';
      tdi   <= '0';
      update <= '1'; tick; update <= '0';
    end procedure scan_in;

    -- Output phase: Capture-DR, NUM_OUT Shift-DR cycles, Update-DR.
    --
    -- tdo is sampled while tck is LOW, immediately before the rising edge.
    -- That is precisely what an MPSSE +ve-edge read sees, so this exercises
    -- the falling-edge launch: the value read must be the one launched half a
    -- period earlier, not the one the register is moving to on this edge.
    procedure scan_out (signal result : out std_logic_vector(NUM_OUT-1 downto 0)) is
      variable r : std_logic_vector(NUM_OUT-1 downto 0);
    begin
      capture <= '1'; tick; capture <= '0';
      shift <= '1';
      for i in 0 to NUM_OUT-1 loop
        r(i) := tdo;      -- sampled at the rising edge, LSB first
        tick;
      end loop;
      shift <= '0';
      update <= '1'; tick; update <= '0';
      result <= r;
    end procedure scan_out;

    variable expected : std_logic_vector(NUM_OUT-1 downto 0);
    variable vec      : std_logic_vector(NUM_IN-1 downto 0);
    variable detected : integer := 0;

    -- scan_out needs a signal to write through; a shared variable would do but
    -- a signal keeps this VHDL-93 clean.
    procedure check (got : std_logic_vector(NUM_OUT-1 downto 0);
                     exp : std_logic_vector(NUM_OUT-1 downto 0);
                     ctx : string) is
    begin
      checks <= checks + 1;
      if got /= exp then
        errors <= errors + 1;
        report ctx & ": expected " & to_str(exp) & " got " & to_str(got)
          severity error;
      end if;
    end procedure check;

  begin

    ----------------------------------------------------------------------------
    report "=== tb_scan_core starting ===" severity note;
    ----------------------------------------------------------------------------
    tap_reset;
    assert io_phase = '0'
      report "TEST 0 FAILED: io_phase not cleared by jtag_reset" severity error;

    ----------------------------------------------------------------------------
    -- TEST 1 -- exhaustive scan
    ----------------------------------------------------------------------------
    report "TEST 1: exhaustive scan of all " & integer'image(2**NUM_IN)
         & " input vectors" severity note;

    for n in 0 to 2**NUM_IN - 1 loop
      vec      := std_logic_vector(to_unsigned(n, NUM_IN));
      expected := dut_model(vec);
      scan_in(vec);
      scan_out(result_sig);
      wait for 0 ns;
      check(result_sig, expected, "TEST 1 vector " & integer'image(n));
    end loop;

    ----------------------------------------------------------------------------
    -- TEST 2 -- desync recovery via TAP reset  (KNOWN_ISSUES #1)
    --
    -- Abandon a vector after its input phase. io is left at '1', so host and
    -- FPGA now disagree about whose turn it is. On the ORIGINAL code this was
    -- unrecoverable and every later vector was wrong. With the reset path, a
    -- TAP reset restores the phase.
    ----------------------------------------------------------------------------
    report "TEST 2: desync recovery via jtag_reset" severity note;

    vec := std_logic_vector(to_unsigned(16#A5#, NUM_IN));
    scan_in(vec);                     -- input phase only: io left at '1'
    assert io_phase = '1'
      report "TEST 2 setup: expected io_phase = '1' after a lone input phase"
      severity error;

    tap_reset;
    assert io_phase = '0'
      report "TEST 2 FAILED: jtag_reset did not clear io_phase -- this is the "
           & "bug KNOWN_ISSUES #1 describes"
      severity error;

    vec      := std_logic_vector(to_unsigned(16#3C#, NUM_IN));
    expected := dut_model(vec);
    scan_in(vec);
    scan_out(result_sig);
    wait for 0 ns;
    check(result_sig, expected, "TEST 2 post-reset vector");

    ----------------------------------------------------------------------------
    -- TEST 3 -- desync recovery via deselect
    --
    -- Same situation, but recovering the way it happens in practice when the
    -- TAP moves to another instruction -- e.g. Vivado Hardware Manager taking
    -- the chain between runs.
    ----------------------------------------------------------------------------
    report "TEST 3: desync recovery via sel = '0'" severity note;

    vec := std_logic_vector(to_unsigned(16#5A#, NUM_IN));
    scan_in(vec);                     -- io left at '1' again
    sel <= '0'; tick; sel <= '1';
    assert io_phase = '0'
      report "TEST 3 FAILED: deselect did not clear io_phase" severity error;

    vec      := std_logic_vector(to_unsigned(16#77#, NUM_IN));
    expected := dut_model(vec);
    scan_in(vec);
    scan_out(result_sig);
    wait for 0 ns;
    check(result_sig, expected, "TEST 3 post-deselect vector");

    ----------------------------------------------------------------------------
    -- TEST 4 -- bit-order sensitivity
    --
    -- Shift every vector in backwards and require that at least one comes back
    -- wrong. Without this, a testbench blind to bit order would look identical
    -- to one that works -- and reversed bit order is the most common mistake
    -- when adapting the harness to a new DUT.
    --
    -- Why a sweep and not one vector: for some vectors the golden model gives
    -- the same answer forwards and backwards, so a single unlucky choice can
    -- pass a broken testbench. (An offline model of this design showed exactly
    -- that -- 64 of 256 vectors are reversal-blind under this model, and the
    -- vector originally chosen here was one of them.) Sweeping removes the
    -- dependence on picking a good vector, and on the model and widths staying
    -- as they are.
    ----------------------------------------------------------------------------
    report "TEST 4: bit-order sensitivity (reversed vectors must be detected)"
      severity note;

    tap_reset;
    detected := 0;
    for n in 0 to 2**NUM_IN - 1 loop
      vec      := std_logic_vector(to_unsigned(n, NUM_IN));
      expected := dut_model(vec);
      scan_in(vec, reversed => true);
      scan_out(result_sig);
      wait for 0 ns;
      if result_sig /= expected then
        detected := detected + 1;
      end if;
    end loop;

    checks <= checks + 1;
    report "TEST 4: " & integer'image(detected) & " of "
         & integer'image(2**NUM_IN) & " reversed vectors detected as wrong"
      severity note;

    if detected = 0 then
      errors <= errors + 1;
      report "TEST 4 FAILED: no reversed vector was detected -- this testbench "
           & "is blind to bit order and TEST 1 proves nothing"
        severity error;
    end if;

    ----------------------------------------------------------------------------
    -- Summary
    ----------------------------------------------------------------------------
    wait for 0 ns;
    report "=== tb_scan_core done: " & integer'image(checks) & " checks, "
         & integer'image(errors) & " errors ===" severity note;

    if errors = 0 then
      report "ALL TESTS PASSED" severity note;
    else
      report "TESTS FAILED" severity failure;
    end if;

    wait;
  end process stim;

end architecture sim;
