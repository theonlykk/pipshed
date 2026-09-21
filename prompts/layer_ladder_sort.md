This message has a line count at the bottom

# PIPSHED: SHOW THE LADDER IN PRICE ORDER, WITH GAPS

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Ask | operator, 2026-09-21: order the instance layer table by decreasing price, to see how far apart the triggers are | -- |
| Baseline | pipshed `origin/main` at `36a4ade` | read by Claude |
| Scope | `templates/dashboard.html` only: `renderGrindLayerTableHtml` and its two call sites | this spec |
| Tests | pipshed has no JavaScript tests; verification is a visual check by the operator | -- |

## BRANCH

`feat/layer-ladder-order` from `origin/main`. ONE commit plus a response
doc. Push. Do NOT merge -- merging to `main` deploys to Railway.

## CONTEXT

- `renderGrindLayerTableHtml(layers)` (`templates/dashboard.html:1370`)
  renders the `#`, `Side`, `Entry`, `Exit`, `Covered` table in the order
  the EA sends layers -- which is not price order.
- Called at `:1337` (`data.layers`) and `:2166` (`card.layers`).
- Pending entries are shown separately by `renderGrindPendingLine`
  (`:1390`), from `card.add_pending_long`, `add_pending_short`,
  `l0_pending_long`, `l0_pending_short` (prices, or null).

## DESIGN

Change the signature to `renderGrindLayerTableHtml(layers, card)` and
update BOTH call sites to pass the card object (`data` at `:1337`, `card`
at `:2166`).

Build one list of rows:

1. every layer, with `price = entry_price`, `kind = 'layer'`
2. for each non-null of `add_pending_long`, `add_pending_short`,
   `l0_pending_long`, `l0_pending_short`: a row with that price,
   `kind = 'pending'`, side L or S, label `add` or `L0`

Sort by price, **descending**. Rows with a null price sort last.

Columns: `#`, `Side`, `Entry`, `Gap`, `Exit`, `Covered`.

- `#`: the layer index for layers; `add` or `L0` for pending rows.
- `Entry`: the price, 5 decimals (keep the existing `toFixed(5)`).
- `Gap`: pips between this row's price and the row ABOVE it, one decimal,
  no sign. **Empty if this is the first row, OR if either this row's
  price or the price above it is null.** Test for null explicitly --
  in JavaScript `null` coerces to 0, which would print a gap of about
  13,000 pips. Pip size: `0.01` if price > 20, else `0.0001`.
- **Header:** change the `<thead>` string in `renderGrindLayerTableHtml`
  to `<th>#</th><th>Side</th><th>Entry</th><th>Gap</th><th>Exit</th><th>Covered</th>`
  so it matches the six cells in each row.
- `Exit` and `Covered`: as today for layers; `--` for pending rows.
- Pending rows get class `grind-pending-row`; add one CSS rule next to the
  existing `.grind-layer-table` rules: `font-style: italic; opacity: 0.7;`

Keep `renderGrindPendingLine` and its output unchanged.

## NEGATIVE SPACE

- Only `templates/dashboard.html`. No change to `app.py`, the API, the
  worker or any migration.
- Do not remove or rename any existing element id.
- No new dependencies. ASCII only. Stage by exact path. No merge, no PR.

## RESPONSE FORMAT

`prompts/layer_ladder_sort_response.md`: commit hash AS IT EXISTS ON
ORIGIN, diff stat, and a before/after example of the rendered rows for
the GBPUSD OPT layers below, worked by hand from the code you wrote:

    entries L: 1.34009 1.34187 1.34338 1.34450 1.33909 1.33809 1.33710
    entries S: 1.33698 1.33594 1.33445
    add_pending_long 1.33610, add_pending_short 1.33798, L0s null

Footer: true line count. Reply in chat with ONLY the branch, the hash,
and one line saying it is pushed.

Line count: 82
