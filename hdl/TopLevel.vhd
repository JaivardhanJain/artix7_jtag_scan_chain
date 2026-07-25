library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity TopLevel is
end TopLevel;

architecture Struct of TopLevel is

  ----------------------------------------------------------------
  -- DUT I/O configuration
  ----------------------------------------------------------------
  constant number_of_inputs  : integer := 7;
  constant number_of_outputs : integer := 1;
  ----------------------------------------------------------------

  component DUT is
    port (
      input_vector  : in  std_logic_vector(number_of_inputs-1 downto 0);
      output_vector : out std_logic_vector(number_of_outputs-1 downto 0)
    );
  end component;

  ----------------------------------------------------------------
  -- Vivado JTAG primitive
  ----------------------------------------------------------------
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

  ----------------------------------------------------------------
  -- Internal signals
  ----------------------------------------------------------------
  signal tck   : std_logic;
  signal tdi   : std_logic;
  signal tdo   : std_logic;
  signal sdr   : std_logic;
  signal cdr   : std_logic;
  signal udr   : std_logic;

  signal data      : std_logic_vector(number_of_inputs-1 downto 0)
                      := (others => '0');
  signal datau     : std_logic_vector(number_of_outputs-1 downto 0)
                      := (others => '0');
  signal dut_input : std_logic_vector(number_of_inputs-1 downto 0)
                      := (others => '0');
  signal dut_output: std_logic_vector(number_of_outputs-1 downto 0);

  signal io : std_logic := '0';  -- 0 = input phase, 1 = output phase

begin

  ----------------------------------------------------------------
  -- BSCANE2 instance (USER1)
  ----------------------------------------------------------------
  bscan_inst : BSCANE2
    generic map ( JTAG_CHAIN => 1 )
    port map (
      TCK     => tck,
      TDI     => tdi,
      TDO     => tdo,
      SHIFT   => sdr,
      CAPTURE => cdr,
      UPDATE  => udr,
      RESET   => open,
      RUNTEST => open,
      DRCK    => open,
      SEL     => open
    );

  ----------------------------------------------------------------
  -- Scan chain logic (IEEE-1149.1 correct)
  ----------------------------------------------------------------
  shift_reg : process(tck)
  begin
    if rising_edge(tck) then

      -- UPDATE-DR (one-cycle pulse)
      if udr = '1' then
        io <= not io;
        if io = '0' then
          -- latch input vector into DUT
          dut_input <= data;          
        end if;

      -- CAPTURE-DR
      elsif cdr = '1' then
        if io = '1' then
          -- capture DUT output into scan register
          datau <= dut_output;
        end if;

      -- SHIFT-DR
      elsif sdr = '1' then
        if io = '0' then
          -- shift input bits (LSB-first)
          if number_of_inputs = 1 then
            data(0) <= tdi;
          else
            data <= tdi & data(number_of_inputs-1 downto 1);
          end if;
        else
          -- shift output bits (LSB-first)
          if number_of_outputs = 1 then
            datau(0) <= '0';
          else
            datau <= '0' & datau(number_of_outputs-1 downto 1);
          end if;
        end if;
      end if;


    end if;
  end process;

  ----------------------------------------------------------------
  -- DUT instance
  ----------------------------------------------------------------
  dut_instance : DUT
    port map (
      input_vector  => dut_input,
      output_vector => dut_output
    );

  ----------------------------------------------------------------
  -- JTAG TDO (must be combinational)
  ----------------------------------------------------------------
  tdo <= datau(0);

  ----------------------------------------------------------------
  -- Debug output (logic analyzer friendly)
  -- [4]=SHIFT, [3]=CAPTURE, [2]=UPDATE, [1]=IO, [0]=DUT MSB
  ----------------------------------------------------------------
  --state_out <= sdr & cdr & udr & io & dut_output(number_of_outputs-1);

end Struct;
