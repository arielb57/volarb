# volarb

Find static arbitrage in option quote grids, and the fewest quotes to drop to remove it.

## The problem

Vol surfaces from generative models, broker feeds and hand-tuned interpolators
often break no-arbitrage: call prices rise with strike, butterflies are worth
less than zero, calendar spreads are worth less than zero. The usual check is a
float tolerance on a finite-difference second derivative. It flags a region but
does not say which quotes cause it, and a tolerance can hide a real violation
or invent one. Someone cleaning a grid before calibration needs a different
answer: the smallest set of quotes to throw away so that what remains is
arbitrage-free.

volarb checks the grid in exact rational arithmetic, names the quotes behind
every violation, and computes a minimum removal set per expiry.

## How it works

**Exact input.** Prices, strikes, forwards and discount factors are read as
decimal strings straight into `fractions.Fraction`. Every comparison is exact.
If the grid holds implied vols, they go through a stdlib Black-76 (`math.erfc`
in the tails, put-call parity for in-the-money strikes). That conversion is the
only float step, and the report says when it happened. The converted price is
clamped to the exact bounds, because the true Black price always lies inside
them and only rounding can push it out.

**Checks per expiry** (quotes sorted by strike, identical duplicates merged):

| kind | condition | size reported |
|---|---|---|
| `upper_bound` | C ≤ DF·F | C − DF·F |
| `lower_bound` | C ≥ max(DF·(F−K), 0) | bound − C |
| `duplicate_strike` | one price per strike | price spread |
| `monotonicity` | slope between neighbours ≤ 0 | price rise |
| `vertical_spread` | slope ≥ −DF | spread value − DF·width |
| `convexity` | second divided difference 2(s₂−s₁)/(K₃−K₁) ≥ 0 on non-uniform strikes | its negative |
| `calendar` | see below | gap in C/(DF·F) |

The convexity check includes the model-free point C(0) = DF·F as a phantom
left neighbour of the first quote. Without it, a slice such as C(50)=99,
C(60)=94 with F=100 passes every local test, even though a butterfly
through K=0 is worth less than zero.

**Calendar check.** Assuming zero dividends and forwards proportional across
expiries, the normalised price c = C/(DF·F) at equal moneyness K/F cannot
fall as maturity grows. For adjacent expiries, each quote of the earlier one
is compared with the later expiry's linear interpolant at the same K/F
(an exact match if the strike is on the grid). The comparison runs one way on
purpose. A chord lies on or above every convex curve through its endpoints,
so `earlier > chord(later)` is arbitrage whatever the later slice does between
its quotes. The reverse comparison proves nothing, so it is not made.

**Minimum removal.** For one expiry, the quotes to keep form a path through
the distinct (strike, price) points, starting at the fixed point (0, DF·F).
An edge i→j is allowed when both points are within bounds and the slope is in
[−DF, 0]. Two consecutive edges must have non-decreasing slope. The heaviest
such path (weight = number of quotes at the point) is the largest
arbitrage-free subset, and its complement is the minimum removal set. The
textbook DP over (previous, current) pairs is O(n³). volarb keeps the incoming
edges of each node sorted by slope with running maxima, so "best path into i
whose last slope is ≤ s" becomes a binary search. That gives O(n² log n).

Worked example, `examples/broker.csv` (second expiry):

```
K      90     100    102.5   110    120
C      13.90  6.40   5.90    1.35   0.95
slope      -0.75  -0.20  -0.607  -0.04
```

The slope falls from −0.20 to −0.607 at K=102.5, so the 100/102.5/110 butterfly
is negative. Dropping any one of the three fixes it, and the DP returns one of them.

**Surface report.** `analyze()` lists every violation, removes each expiry's
minimum set, then clears any remaining calendar violations greedily by
dropping the earlier quote of the largest one. Removing a quote keeps a slice
arbitrage-free and can only raise the chords that calendar comparisons use,
so the greedy loop never creates a new violation. It then re-checks the
repaired surface and reports how many violations remain, which should be zero.

**Synthetic surfaces.** `volarb.synth` generates raw-SVI slices,
w(k) = a + b(ρ(k−m) + √((k−m)² + σ²)), priced with Black-76. It samples
parameters that satisfy the Gatheral–Jacquier condition g(k) ≥ 0, and it
injects arbitrage in exact arithmetic:

- `inject_bump`: lifts one quote above the chord of its neighbours, by half
  the room left before monotonicity would also break. Creates exactly one
  convexity violation.
- `inject_tilt`: adds a rising linear tilt from one strike on. Creates
  monotonicity violations on every tilted pair and nothing else.
- `inject_calendar_crossing`: replaces the later slice by a mix of intrinsic
  value and the earlier slice. Creates calendar violations exactly at the
  earlier quotes with positive time value.

## Install and usage

Requires Python 3.10+. No runtime dependencies. From a clone of this repository:

```
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The CSV needs the columns `expiry,t,forward,discount,strike` plus either
`price` or `iv`. Exit code 0 means no arbitrage, 1 means violations were
found, and 2 means the input could not be read.

```
$ volarb check examples/broker.csv
13 quotes in 2 expiries
2 violations: 1 calendar, 1 convexity

kind       expiry            quotes                                       size
---------  ----------------  -------------------------------------------  ----------
calendar   2026-12->2027-03  2026-12@K=110 2027-03@K=110 2027-03@K=120    0.00246198
convexity  2027-03           2027-03@K=100 2027-03@K=102.5 2027-03@K=110  0.0813333

minimum removal: 2 of 13 quotes
  2027-03: K = 100  (lines 11)
  calendar (greedy, not proven minimal):
    2026-12: K = 110  (line 7)
violations after removal: 0
```

Implied vols:

```
$ volarb check examples/vols.csv
14 quotes in 2 expiries
note: prices were computed from implied vols with float Black-76 (math.erfc); that conversion is the only inexact step, and violations of size ~1e-12 or below may be rounding in it
1 violations: 1 calendar

kind      expiry  quotes             size
--------  ------  -----------------  -----------
calendar  1M->3M  1M@K=115 3M@K=115  0.000237391

minimum removal: 1 of 14 quotes
  calendar (greedy, not proven minimal):
    1M: K = 115  (line 8)
violations after removal: 0
```

`--json` prints exact sizes as fractions (`"size": "61/750"`), the quotes by
CSV line number, and the removal sets. Synthetic grids:

```
$ volarb generate --seed 1 --expiries 2 --strikes 8 --inject tilt > grid.csv
$ volarb check grid.csv
16 quotes in 2 expiries
2 violations: 2 monotonicity

kind          expiry  quotes                   size
------------  ------  -----------------------  ---------
monotonicity  T1      T1@K=124.75 T1@K=143.25  0.185
monotonicity  T1      T1@K=143.25 T1@K=145.5   0.0659883

minimum removal: 2 of 16 quotes
  T1: K = 143.25, 145.5  (lines 8,9)
violations after removal: 0
```

As a library:

```python
from volarb import analyze, check_expiry, min_removal
from volarb.csvio import read_grid_file

surface, from_iv = read_grid_file("examples/broker.csv")
for v in check_expiry(surface.expiry("2027-03")):
    print(v.kind, v.quotes, v.size)          # size is a Fraction
print(min_removal(surface.expiry("2027-03")).removed)
```

## Results

### What the tests prove

- **No false positives.** 60 GJ-compliant SVI slices on random strike grids
  (2–40 strikes, three discount factors) and 20 four-expiry calendar-consistent
  surfaces give zero violations.
- **Injections are precise.** A bump gives exactly one convexity violation at
  the bumped triple (25 seeds). A tilt gives exactly the monotonicity pairs it
  touched (25 seeds). A calendar crossing gives exactly the calendar violations
  predicted, with sizes equal to (1−weight)·time value (15 seeds).
- **DP = brute force.** On 2,000 random messy grids (n ≤ 12, with noise,
  zeros, duplicate strikes and out-of-bound prices), `min_removal` returns the
  same size as full subset enumeration, and the kept set re-checks clean.
  More than 500 of those grids need a non-empty removal.
- **Repairs hold.** Removing the reported set leaves zero violations on 200
  grids of up to 40 quotes and on surfaces with all three injections at once.
- **Edge cases** have dedicated tests: duplicate strikes (identical and
  conflicting), a single quote, an empty expiry, zero-price wings, strikes
  exactly at the forward, and calendar checks on mismatched strike grids.

The full suite (406 tests) runs in about 10 seconds.

### Naive SVI slices that break Gatheral–Jacquier

`python bench/svi_gj_table.py`: 61 strikes with log-moneyness evenly spaced in
[−1.5, 1.5], F=100, DF=1, T=1. "Vogt" is the parameter set Gatheral and
Jacquier use as their counterexample. The naive rows are raw SVI draws with
no butterfly constraint, kept when min g < 0 on the range. Violations of size
below 1e-12 come from float rounding in Black-76 and are counted in a separate
column.

| slice | a, b, rho, m, sigma | min g | convexity | monotonicity | other | size < 1e-12 | flagged k range | min removal (of 61) |
|---|---|---|---|---|---|---|---|---|
| Vogt | -0.0410, 0.1331, +0.306, +0.359, 0.415 | -0.0329 | 13 | 9 | 0 | 0 | +0.50 .. +1.30 | 17 |
| naive-1 | 0.0120, 0.2220, +0.607, +0.218, 0.154 | -0.0513 | 7 | 0 | 0 | 0 | +0.40 .. +0.80 | 9 |
| naive-2 | 0.0066, 0.0961, +0.730, +0.275, 0.092 | -0.1013 | 7 | 5 | 0 | 0 | +0.30 .. +0.75 | 9 |
| naive-3 | 0.0079, 0.2349, +0.927, +0.273, 0.195 | -0.1274 | 13 | 8 | 0 | 0 | +0.35 .. +1.10 | 17 |
| naive-4 | -0.0042, 0.2084, +0.913, +0.094, 0.188 | -0.0079 | 2 | 0 | 0 | 2 | +0.35 .. +0.50 | 4 |
| naive-5 | -0.0048, 0.1113, +0.782, +0.191, 0.144 | -0.1035 | 8 | 5 | 0 | 0 | +0.20 .. +0.70 | 10 |
| naive-6 | -0.0040, 0.2306, +0.134, +0.120, 0.063 | -0.2704 | 8 | 5 | 0 | 0 | +0.15 .. +0.65 | 10 |
| GJ-ok | -0.0046, 0.2134, +0.501, -0.147, 0.258 | +0.2023 | 0 | 0 | 0 | 0 | - | 0 |

In every broken slice the flagged strikes sit where g < 0. The negative
density is strong enough in five of the seven to make call prices rise with
strike, not just lose convexity.

### min_removal runtime

`python bench/bench_min_removal.py` (about a minute; `--quick` stops at n=16).
Measured on an Apple Silicon Mac (arm64, macOS), CPython 3.12.13, single thread.
Grids are Black-76 prices rounded to cents with ±5% noise, median of 3 grids
per n. Brute force tries subsets from largest to smallest and stops at the
first clean one, so its cost depends on how many quotes must go.

| n | removed (median) | DP median | brute force median | ratio |
|---|---|---|---|---|
| 8 | 3 | 0.16 ms | 2.4 ms | 15x |
| 9 | 2 | 0.14 ms | 1.9 ms | 13x |
| 10 | 2 | 0.18 ms | 1.4 ms | 7x |
| 11 | 3 | 0.21 ms | 4.9 ms | 23x |
| 12 | 5 | 0.20 ms | 26.2 ms | 133x |
| 13 | 5 | 0.26 ms | 53.4 ms | 207x |
| 14 | 4 | 0.27 ms | 42.3 ms | 157x |
| 15 | 4 | 0.31 ms | 51.5 ms | 165x |
| 16 | 5 | 0.41 ms | 217.0 ms | 535x |
| 17 | 7 | 0.42 ms | 1046.6 ms | 2,487x |
| 18 | 8 | 0.50 ms | 2612.0 ms | 5,238x |
| 19 | 7 | 0.50 ms | 2783.8 ms | 5,537x |
| 20 | 8 | 0.61 ms | 8585.6 ms | 14,188x |

Larger grids, DP only. The second row of each pair is the DP's worst case: a
strictly convex slice, where every pair of quotes is a feasible edge.

| n | grid | removed | DP time |
|---|---|---|---|
| 50 | 2% noise, cents | 20 | 4 ms |
| 50 | arbitrage-free, all edges feasible | 0 | 4 ms |
| 100 | 2% noise, cents | 54 | 16 ms |
| 100 | arbitrage-free, all edges feasible | 0 | 18 ms |
| 200 | 2% noise, cents | 136 | 72 ms |
| 200 | arbitrage-free, all edges feasible | 0 | 78 ms |

Exact timings vary by machine; the shape of the curves does not.

## Design notes

**Exactness over tolerance, and the zero-strike anchor.** A tolerance
changes the question from "is there arbitrage?" to "is there arbitrage larger
than ε in some unit?". It also breaks the equivalence the repair depends on:
with a tolerance, a subset of a passing grid can fail. With exact
comparisons, "these quotes are arbitrage-free" is a property of consecutive
triples, so the DP's local transition rule is exactly the checker's
definition. The 2,000-grid brute-force test confirms that directly. The price
is that float-derived prices (implied vols, or the SVI generator) can show
violations of size 1e-15. volarb reports them rather than hiding them, flags
float inputs, and clamps only where clamping is provably harmless (the static
bounds). Adding C(0) = DF·F as a fixed anchor was the other decision that
mattered. It turned up a real bug in the first version of the synthetic
generator: the Gatheral–Jacquier condition had only been checked on the quoted
moneyness range, and negative density in the unquoted left wing made the
quotes inconsistent with a zero-strike call. The generator now checks g on
[−8, 8] and the wing bound b(1+|ρ|) < 2.

**Per-expiry optimality, greedy calendars.** Joint minimum removal across
expiries couples the slices through interpolated chords, and the problem stops
being a path problem. volarb keeps the part it can prove (per-expiry minimum,
O(n² log n)) and handles calendars greedily, with an argument that the greedy
step never makes things worse. The report labels the calendar part as not
proven minimal.

## Limitations

- **Calendar removal is not jointly minimal.** The per-expiry sets are the
  smallest possible for each expiry alone. The calendar step is greedy, and
  the per-expiry DP breaks ties without looking at other expiries. When one
  quote could fix both a butterfly and a calendar violation, volarb can drop
  more quotes than necessary. (`examples/broker.csv` needs 2 removals, and
  volarb finds 2; the tests do not bound the surface-wide gap.)
- Calendar checks assume zero dividends and forwards proportional across
  expiries, compare only adjacent expiries, and skip earlier quotes outside
  the later expiry's strike range.
- Only European calls. Puts must be converted by parity first. Bid/ask
  spreads are not modelled: each quote is one price.
- No tolerance option. Grids built from floats can show tiny violations that
  come from rounding. Violation sizes let you judge them, but volarb will not
  filter them for you.
- The Gatheral–Jacquier check in the generator samples g on a grid of 4001
  points. It is a numerical check, not a proof, and the margin (g ≥ 1e-3)
  covers the gaps.
- For conflicting duplicate strikes, pair and triple checks that span the
  duplicate are skipped and the duplicate is reported instead. The removal
  set still resolves both.

## License

MIT. See [LICENSE](LICENSE).
