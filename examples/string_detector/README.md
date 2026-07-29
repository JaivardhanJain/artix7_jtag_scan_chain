# Example: String Detector

A sequential design that asserts its output when a target character sequence is seen on a 5-bit input.

## The design

Three independent Mealy FSMs — `RunDetector`, `CryDetector`, `BroomDetector` — detecting the subsequences `run`, `cry` and `broom` in a stream of 5-bit characters (a=1 … z=26, space=0). Their outputs are ORed. Subsequence, not substring: on a mismatch each FSM holds its state rather than falling back to the start.

`broom` is the interesting one — the doubled `o` needs its own state.

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

**Sources recovered, but deliberately not published.** `StringDetector.vhdl` and its three sub-detectors (`RunDetector`, `CryDetector`, `BroomDetector`) were recovered from the original MAX 10 lab material and are present in a local working copy, so this example builds and runs. They are **gitignored**: they are filled-in solutions to a teaching lab that may still be assigned. See [../README.md](../README.md).

If you have the four detector files, drop them in this folder and it builds. Otherwise use [`../seq1011`](../seq1011), which is complete and self-contained.

### Provenance

The recovered sources were confirmed correct before use, not assumed: replaying all 46 tracefile vectors through a model of the three FSMs reproduces the expected column exactly, 0 mismatches on the 44 unmasked vectors. The hidden input stream decodes to `" bringunocardsfrommybag"`, which contains `b-r-o-o-m`, `r-u-n` and `c-r-y` as subsequences — the three patterns the detector ORs together.

Two variants of the lab existed with different tracefiles. This repository's tracefile is a byte-for-byte match with the Friday variant, which is the one installed.

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
