--------------------------------------------------------------------------------
-- TopLevel
--------------------------------------------------------------------------------
-- Top level of the JTAG scan chain harness. Has NO ports: every input and
-- output travels over the FPGA's JTAG TAP, so no board I/O is consumed.
--
-- This file is now only the Xilinx-specific wiring -- BSCANE2 to scan_core to
-- DUT. All scan logic lives in scan_core.vhd, which contains no vendor
-- primitives and can therefore be simulated without the unisim library.
--
-- To retarget the harness at a different design, edit the two constants below
-- to match your DUT's port widths, and supply a DUT.vhd whose entity matches
-- the component declared here. (scripts/new_lab.py will generate both -- see
-- docs/ROADMAP.md Phase 4.)
--
-- Original implementation by Anubhav Bhura, Wadhwani Electronics Laboratory,
-- IIT Bombay.
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity TopLevel is
end entity TopLevel;

architecture Struct of TopLevel is

  ------------------------------------------------------------------------------
  -- DUT I/O configuration -- edit these two to match your DUT
  ------------------------------------------------------------------------------
  constant number_of_inputs  : integer := 7;
  constant number_of_outputs : integer := 1;
  ------------------------------------------------------------------------------

  component DUT is
    port (
      input_vector  : in  std_logic_vector(number_of_inputs-1 downto 0);
      output_vector : out std_logic_vector(number_of_outputs-1 downto 0)
    );
  end component;

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

  ------------------------------------------------------------------------------
  -- Xilinx JTAG primitive. JTAG_CHAIN => 1 binds this instance to the USER1
  -- instruction (6-bit IR value 0x02 on 7-series).
  ------------------------------------------------------------------------------
  component BSCANE2
    generic (
      JTAG_CHAIN : integer := 1
    );
    port (
      TCK     : out std_logic;
      TDI     : out std_logic;
      TDO     : in  std_logic;
      SHIFT   : out std_logic;
      CAPTURE : out std_logic;
      UPDATE  : out std_logic;
      RESET   : out std_logic;
      RUNTEST : out std_logic;
      DRCK    : out std_logic;
      SEL     : out std_logic
    );
  end component;

  signal tck        : std_logic;
  signal tdi        : std_logic;
  signal tdo        : std_logic;
  signal sdr        : std_logic;
  signal cdr        : std_logic;
  signal udr        : std_logic;
  signal jtag_reset : std_logic;
  signal sel        : std_logic;

  signal dut_input  : std_logic_vector(number_of_inputs-1 downto 0);
  signal dut_output : std_logic_vector(number_of_outputs-1 downto 0);

begin

  ------------------------------------------------------------------------------
  -- BSCANE2 (USER1)
  --
  -- RESET and SEL are now connected. They were previously left `open`, which
  -- is what left the io phase bit with no way to resynchronise after an
  -- interrupted run -- see docs/KNOWN_ISSUES.md #1.
  ------------------------------------------------------------------------------
  bscan_inst : BSCANE2
    generic map ( JTAG_CHAIN => 1 )
    port map (
      TCK     => tck,
      TDI     => tdi,
      TDO     => tdo,
      SHIFT   => sdr,
      CAPTURE => cdr,
      UPDATE  => udr,
      RESET   => jtag_reset,
      SEL     => sel,
      RUNTEST => open,
      DRCK    => open
    );

  ------------------------------------------------------------------------------
  -- Scan chain logic
  ------------------------------------------------------------------------------
  scan_inst : scan_core
    generic map (
      number_of_inputs  => number_of_inputs,
      number_of_outputs => number_of_outputs
    )
    port map (
      tck        => tck,
      tdi        => tdi,
      tdo        => tdo,
      capture    => cdr,
      shift      => sdr,
      update     => udr,
      jtag_reset => jtag_reset,
      sel        => sel,
      dut_input  => dut_input,
      dut_output => dut_output,
      io_phase   => open
    );

  ------------------------------------------------------------------------------
  -- Design under test
  ------------------------------------------------------------------------------
  dut_instance : DUT
    port map (
      input_vector  => dut_input,
      output_vector => dut_output
    );

  ------------------------------------------------------------------------------
  -- Debug output for a logic analyser. To use it, add
  --   port ( state_out : out std_logic_vector(4 downto 0) );
  -- to the entity above, uncomment the line below, and assign five pins in
  -- constraints.xdc. [4]=SHIFT [3]=CAPTURE [2]=UPDATE [1]=io [0]=DUT MSB
  -- (io_phase would need to be wired to a signal instead of `open`.)
  ------------------------------------------------------------------------------
  -- state_out <= sdr & cdr & udr & io_phase_sig & dut_output(number_of_outputs-1);

end architecture Struct;
