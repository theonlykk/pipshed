This message has a line count at the bottom

# layer ladder sort -- execution report

## Prompt read at

Commit `805a8ff` (file ended with `Line count: 82`).

## Branch

`feat/layer-ladder-order`

## Commit on origin

`17e0e09` (implementation); response doc on same branch after push.

## Diff stat

```
 templates/dashboard.html | 78 insertions(+), 16 deletions(-)
 1 file changed, 78 insertions(+), 16 deletions(-)
```

## Before / after (GBPUSD OPT example, hand-worked)

Inputs:

- Layer entries L: 1.34009, 1.34187, 1.34338, 1.34450, 1.33909, 1.33809, 1.33710
- Layer entries S: 1.33698, 1.33594, 1.33445
- `add_pending_long` 1.33610, `add_pending_short` 1.33798, L0 pending null
- Pip size 0.0001 (all prices below 20)

**Before:** rows in EA send order (layer index order), columns `# Side Entry Exit Covered` only.

**After:** rows sorted by Entry descending; pending rows italic; Gap = (price above - this price) / pip:

| # | Side | Entry | Gap | Exit | Covered |
|---|---|---|---|---|---|
| (idx) | long | 1.34450 | | (layer) | (layer) |
| (idx) | long | 1.34338 | 11.2 | ... | ... |
| (idx) | long | 1.34187 | 15.1 | ... | ... |
| (idx) | long | 1.34009 | 17.8 | ... | ... |
| (idx) | long | 1.33909 | 10.0 | ... | ... |
| (idx) | long | 1.33809 | 10.0 | ... | ... |
| add | S | 1.33798 | 1.1 | -- | -- |
| (idx) | long | 1.33710 | 8.8 | ... | ... |
| (idx) | short | 1.33698 | 1.2 | ... | ... |
| add | L | 1.33610 | 8.8 | -- | -- |
| (idx) | short | 1.33594 | 1.6 | ... | ... |
| (idx) | short | 1.33445 | 14.9 | ... | ... |

First row Gap blank; pending rows use `#` add/L0 and Side L/S as coded.

Line count: 54
