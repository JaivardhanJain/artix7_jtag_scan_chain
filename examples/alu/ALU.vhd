library ieee;
use ieee.std_logic_1164.all;
use IEEE.NUMERIC_STD.ALL;
library work;

entity ALU is
	port (A : in std_logic_vector(3 downto 0);
	B : in std_logic_vector(3 downto 0);
	Y : out std_logic_vector(5 downto 0));
end entity;

architecture arch of ALU is 
	function MAX(A : in std_logic_vector(3 downto 0); B : in std_logic_vector(3 downto 0))  return std_logic_vector is
		variable maximum : std_logic_vector(5 downto 0) := (others => '0');
		begin 
			if A > B then
				maximum(3 downto 0) := A;
			elsif A < B then
				maximum(3 downto 0) := B;
			elsif A = B then
				maximum(3 downto 0) := "0000";
			end if;
		return maximum;
	end MAX;
	
	function ANDER(A : in std_logic_vector(3 downto 0); B : in std_logic_vector(3 downto 0))  return std_logic_vector is
		variable anded : std_logic_vector(5 downto 0) := (others => '0');
		begin 
			anded(3 downto 0):= A and B;
		return anded;
	end ANDER;
	
	function ROTATOR(A : in std_logic_vector(3 downto 0); B : in std_logic_vector(3 downto 0))  return std_logic_vector is
		variable rotateanswer : std_logic_vector(5 downto 0) := (others => '0');
		variable combined_bits: std_logic_vector(1 downto 0) := (others => '0');
		begin
			combined_bits:= B(1) & B(0);
			if (B(3) = '1') then 
					rotateanswer(3 downto 0):=std_logic_vector(rotate_right(unsigned(A), to_integer(unsigned(combined_bits))));	
			elsif (B(3) = '0') then 
					rotateanswer(3 downto 0):=std_logic_vector(rotate_left(unsigned(A), to_integer(unsigned(combined_bits))));
			end if;
			return rotateanswer;
	end ROTATOR;
	
	function EQUATOR(A : in std_logic_vector(3 downto 0); B : in std_logic_vector(3 downto 0))  return std_logic_vector is
		variable equateanswer : std_logic_vector(5 downto 0) := (others => '0');
		begin
			if A = B then
				equateanswer(3 downto 0) := A;
			else
				equateanswer(3 downto 0) := "0000";
			end if;
		return equateanswer;
	end EQUATOR;
	
	begin
		alu : process (A, B) 
		begin
			if (A(3) = '0' and B(3) = '0' )then
				Y <= MAX(A, B);
			elsif (A(3) = '1' and B(3) = '0') then
				Y <= ANDER(A, B);
			elsif (A(3) = '0' and B(3) = '1') then
				Y <= ROTATOR(A, B);
			elsif (A(3) = '1' and B(3) = '1') then
				Y <= EQUATOR(A, B);
			else
				y <= "000000";
			end if;
			
		end process;
	
end architecture;

	