# Example: String Detector

A sequential design that asserts its output when a target character sequence is seen on a 5-bit input.

## Interface

```
input_vector(6 downto 2) = inp     -- 5-bit character
input_vector(1)          = reset
input_vector(0)          = clock
output_vector(0)         = outp
```

Set in `hdl/TopLevel.vhd`:

```vhdl
constant number_of_inputs  : integer := 7;
constant number_of_outputs : integer := 1;
```

## Status

⚠️ **This example does not currently elaborate.** `DUT.vhd` instantiates a `StringDetector` component that is not present in this repository — see [../../docs/KNOWN_ISSUES.md](../../docs/KNOWN_ISSUES.md) #5. Supply `StringDetector.vhd` with the port list above to build it.

## Tracefile

46 vectors in `TRACEFILE.txt`, written as clock-low/clock-high pairs so each pair advances the design one cycle:

```
0001000 0 1     <- clock = 0
0001001 0 1     <- clock = 1, edge
```

Note that the first two lines have `mask = 0`, meaning their results are meant to be ignored. The current host script discards the mask column, so they are compared anyway (Known Issues #3).

## Reference result

`../../results/string_detector_output.txt` — 46/46 `Success`, captured from hardware. Use it to confirm a rebuild still behaves identically.

## Run

```
python ../../host/scan_bscane2.py TRACEFILE.txt output.txt
diff output.txt ../../results/string_detector_output.txt
```
