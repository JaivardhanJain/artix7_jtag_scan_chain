--------------------------------------------------------------------------------
-- Seq1011 -- overlapping "1011" sequence detector, Mealy
--------------------------------------------------------------------------------
-- A small clocked design used as the repository's self-contained example. It is
-- deliberately generic: not coursework, so it can live in a public repository.
--
--   din    serial input bit
--   reset  synchronous, active high
--   clock  rising edge
--   detect '1' in the cycle that completes the pattern "1011"
--
-- Overlapping: after detecting "1011", the trailing "1" may start the next
-- match, so the input "1011011" produces two detections rather than one. That
-- makes the state graph slightly more interesting than a reset-on-match design,
-- and it is exactly the kind of subtlety worth catching with a few thousand
-- vectors rather than by hand.
--
--   s0  nothing               s1  seen "1"
--   s2  seen "10"             s3  seen "101"
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity Seq1011 is
  port (
    din    : in  std_logic;
    reset  : in  std_logic;
    clock  : in  std_logic;
    detect : out std_logic
  );
end entity Seq1011;

architecture bhv of Seq1011 is

  type state is (s0, s1, s2, s3);
  signal y_present, y_next : state := s0;

begin

  clock_proc : process(clock)
  begin
    if rising_edge(clock) then
      if reset = '1' then
        y_present <= s0;
      else
        y_present <= y_next;
      end if;
    end if;
  end process clock_proc;

  state_transition_proc : process(din, y_present)
  begin
    case y_present is
      when s0 =>                        -- nothing yet
        if din = '1' then y_next <= s1; else y_next <= s0; end if;
      when s1 =>                        -- "1"
        if din = '0' then y_next <= s2; else y_next <= s1; end if;
      when s2 =>                        -- "10"
        if din = '1' then y_next <= s3; else y_next <= s0; end if;
      when s3 =>                        -- "101"
        -- On '1' the pattern completes. The trailing '1' is also a valid
        -- prefix for the next match, so go to s1, not s0 -- this is what
        -- makes the detector overlapping.
        if din = '1' then y_next <= s1; else y_next <= s2; end if;
    end case;
  end process state_transition_proc;

  -- Mealy output: depends on the present state AND the current input.
  output_proc : process(y_present, din)
  begin
    detect <= '0';
    if y_present = s3 and din = '1' then
      detect <= '1';
    end if;
  end process output_proc;

end architecture bhv;
