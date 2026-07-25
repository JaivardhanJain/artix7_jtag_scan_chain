library ieee;
use ieee.std_logic_1164.all;

-- DUT wrapper for scan chain testing
-- Tracefile format: < 5-bit inp >< reset >< clock >
-- input_vector(6 downto 2) = inp  (5-bit character)
-- input_vector(1)           = reset
-- input_vector(0)           = clock
-- output_vector(0)          = outp

entity DUT is
    port(input_vector  : in  std_logic_vector(6 downto 0);
         output_vector : out std_logic_vector(0 downto 0));
end entity DUT;

architecture Structural of DUT is
    component StringDetector is
        port(inp         : in  std_logic_vector(4 downto 0);
             reset, clock: in  std_logic;
             outp        : out std_logic);
    end component;
begin
    sd: StringDetector port map(
        inp   => input_vector(6 downto 2),
        reset => input_vector(1),
        clock => input_vector(0),
        outp  => output_vector(0));
end architecture Structural;
