# Roadmap

Six phases, ~11–12 hours total across 4–5 sessions. Ordered so the repo is buildable before anything else is attempted.

For the state this project was inherited in, how each defect was found, why the phases are ordered this way, and a defect-to-phase traceability matrix, see [ENGINEERING_LOG.md](ENGINEERING_LOG.md).

**Feasibility: 8.5/10.** The protocol is already proven — 4096/4096 vectors pass on the bundled passthrough test — so there are no unknown-unknowns in the hard part. Phases 1–3 are mechanical. Phase 4 is ordinary scripting. The only genuine engineering is the TDO edge fix and the testbench, and both are bounded.

---

## Phase 1 — Make it build and run reproducibly (~1.5 h)

The project as inherited will not elaborate. This has to come first or nothing below is verifiable.

- [ ] Recover or rewrite `StringDetector.vhd` (Known Issues #5).
- [ ] Decide the fate of `examples/alu/ALU.vhd` — keep as a second worked example with its own tracefile, or drop it.
- [ ] Confirm the physical part from the IDCODE the script prints: `xc7a35tftg256` or `xc7a15tftg256` (Known Issues #6).
- [ ] Replace `hdl/constraints.xdc` with an empty file — no `state_out`, no `UCIO-1` suppression.
- [ ] Rebuild → bitstream → rerun the 46-vector tracefile and confirm parity with `results/string_detector_output.txt`.

**Exit criterion:** a clean clone builds and reproduces a committed result.

## Phase 2 — Fix the two real bugs (~1.5 h)

- [x] **Split the scan logic into `hdl/scan_core.vhd`**, leaving `TopLevel.vhd` as BSCANE2 wiring only. Not originally planned; added because it removes the `unisim` dependency from the scan logic, which is the prerequisite for Phase 5's testbench, and it makes both fixes below local and reviewable.
- [x] Wire `BSCANE2.RESET` (and `SEL`) into a phase reset for `io`; confirm the host's existing TAP reset now self-synchronises every run (Known Issues #1). *Code complete, unverified.*
- [x] Move TDO to a falling-edge register, **or** switch the host to `0x2D`/`0x2F` reads — not both (Known Issues #2). Chose the HDL side: it makes the design spec-compliant for any host. *Code complete, unverified.*
- [ ] **Then sweep the clock divider** from `0x3B` downward and record the fastest reliable setting. Report throughput before vs after. This is the one number in the project that makes a measurable "it's better" claim.
- [ ] Deliberately Ctrl-C mid-run to prove the desync is gone.

**Exit criterion:** an interrupted run recovers without reprogramming, and you have a documented safe clock rate.

## Phase 3 — Harden the host script (~2 h)

Refactor `host/scan_bscane2.py` into `host/scanchain.py`:

- [ ] `argparse`: `--tracefile`, `--out`, `--channel`, `--divider`, `--expect-idcode`, `--verbose`.
- [ ] Tracefile parser: strip CRLF, tolerate whitespace, **validate consistent widths across all lines**, honour the mask column, support `x`/`-` don't-cares, fail loudly with line numbers.
- [ ] Wrap FTDI open in a readable error ("no FTDI device found — is Vivado holding the cable?").
- [ ] Validate the IDCODE against the expected part; abort on mismatch.
- [ ] Compute widths once at parse time instead of leaking them from the write loop (Known Issues #4).
- [ ] Summary block: `N vectors, P pass, F fail, elapsed Xs, Y vectors/s`, plus a failures-only report with vector index, input, expected, got.
- [ ] Non-zero exit code on any failure, so it can gate a script.
- [ ] Delete unused imports and the stale MAX 10 comment; name the `61440` constant.

**Exit criterion:** a malformed tracefile produces a useful error, and a passing run prints one summary line.

## Phase 4 — Automation that makes it plug-and-play (~3 h)

*This is the differentiating work.*

- [ ] **`scripts/build.tcl`** — headless `vivado -mode batch`: create project, add sources, set part, synth + impl + bitstream. No GUI clicking.
- [ ] **`scripts/program.tcl`** — headless Hardware Manager programming (the MAX 10 `program_ScanChain.bat` equivalent).
- [ ] **`scripts/new_lab.py`** — the piece that makes this genuinely reusable. Point it at a student's DUT entity file; it parses the port list and emits:
  - a `DUT.vhd` wrapper with correct bit-slicing,
  - the `number_of_inputs` / `number_of_outputs` constants for `TopLevel.vhd`,
  - a header comment documenting the tracefile column layout.

  Right now every new lab means hand-editing two files and getting the slicing right by hand. That is the actual barrier to anyone else adopting this, and it is fully automatable.
- [ ] **`run.bat` / `Makefile`** — one command: build → program → scan → report.

**Exit criterion:** adding a new lab is one command plus writing a tracefile.

## Phase 5 — Verify without hardware (~2 h)

- [ ] **`sim/tb_scanchain.vhd`** — a behavioural testbench that fakes the BSCANE2 TAP handshake (CAPTURE/SHIFT/UPDATE) and shifts vectors through the real `TopLevel` + DUT.

  Highest-value single addition in the project. It turns a 10-minute synthesise-implement-program-test round trip into a few seconds of simulation, and it catches the two most common student errors — wrong bit order and wrong width — before hardware is involved. The MAX 10 flow never had this.
- [ ] Optional: `openFPGALoader` path so the board can be programmed with no Vivado install — the closest analogue to MAX 10's pre-built `scan-25k.svf`.

**Exit criterion:** a wrong bit order is caught in simulation, not on the bench.

## Phase 6 — Document and compare (~1.5 h)

- [ ] Fold the Phase 2 measurements into `docs/` and close out the resolved entries in `KNOWN_ISSUES.md`.
- [ ] `docs/RESULTS.md`: vectors passed, throughput before/after the divider sweep, defects found and fixed, with the reasoning.
- [ ] A short comparison writeup versus the MAX 10 flow — the artefact to show the professor.

**Exit criterion:** someone who has never seen the repo can go from clone to a passing run using only the docs.

---

## Risks

| Risk | Mitigation |
|---|---|
| `StringDetector.vhd` unrecoverable | Rewrite from the lab spec (~1 h), or substitute a simpler sequential example. |
| Divider sweep shows the current setting is already near the ceiling | A documented "here is the safe operating margin" figure is still a legitimate result. It just becomes a robustness finding rather than a speed win. |
| Phase-reset fix interacts badly with Vivado's own TAP usage | `SEL` deassertion covers the case where Hardware Manager takes the TAP; test with Vivado open and closed. |
| Board part turns out to be the xc7a15t | Only changes the `part` string in `build.tcl` and the expected IDCODE. |

---

## Framing

The honest version of this project's story: the Artix-7 port existed but wasn't reproducible or robust. The work is finding a silent-desync failure mode and a timing race that a passing test suite was hiding, making the build headless, and automating the per-lab wrapper generation that was the real barrier to adoption — then validating it end-to-end on a real lab and documenting it so a student can use it. That's an adoption-ready tool rather than a demo, and it's true.
