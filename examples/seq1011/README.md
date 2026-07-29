# Example: Seq1011 — overlapping "1011" detector

The repository's **self-contained example**. Everything needed to build and run it is committed here, so a fresh clone has something that works end to end.

## Interface

```
input_vector(2) = din
input_vector(1) = reset
input_vector(0) = clock
output_vector(0) = detect
```

Set in `hdl/TopLevel.vhd`:

```vhdl
constant number_of_inputs  : integer := 3;
constant number_of_outputs : integer := 1;
```

## The design

A Mealy FSM that asserts `detect` in the cycle completing the pattern `1011`. It is **overlapping**: after a match, the trailing `1` may begin the next one, so `1011011` produces two detections rather than one.

```
s0 --1--> s1 --0--> s2 --1--> s3 --1--> s1   (and detect = 1)
```

That single transition — `s3` on `1` going to `s1` rather than `s0` — is the whole design. It's also the kind of detail that survives a handful of hand-written vectors and fails on real input, which is what a few hundred automated vectors are for.

## Tracefile

Generated, not hand-written:

```
python3 examples/seq1011/gen_tracefile.py
```

602 vectors (a reset pair plus 300 stimulus bits × 2), 19 detections. The seed is fixed, so regenerating produces an identical file and a diff is meaningful. The stimulus splices in `1011`, `1011011` and `101101011` explicitly so the overlap cases are guaranteed present rather than left to chance.

## The trap this example demonstrates

A clocked DUT needs **two vectors per clock cycle**, and for a Mealy output the expected value **differs between them**:

```
100 0 1     <- clock low:  state has not advanced; mealy(state, din)
101 1 1     <- clock high: edge fired; mealy(next_state, din)
```

Writing the same expected value on both lines is the natural first guess, and it is wrong. It was wrong here: the first version of `gen_tracefile.py` did exactly that, and an independent transcription of `Seq1011.vhd`'s case statement disagreed with it on **65 of 600** vectors. On hardware that would have looked exactly like a broken harness.

The bundled string-detector tracefile shows the correct shape too — detections appear as `1` on the clock-low line and `0` on the clock-high line that follows.

## Verification status

The tracefile is cross-checked against a transcription of the RTL's case statement, read from the VHDL rather than from the generator: **600 unmasked vectors, 0 mismatches**. That catches a mismatch between the design and its expected values.

It does **not** confirm that `Seq1011.vhd` compiles or synthesises — nothing has run it through a VHDL toolchain yet.

## Run

```
vivado -mode batch -source scripts/build.tcl -tclargs examples/seq1011
vivado -mode batch -source scripts/program.tcl
python host/scanchain.py -t examples/seq1011/TRACEFILE.txt -o output.txt
```

Remember to set the width constants in `hdl/TopLevel.vhd` to 3 / 1 first.
