# First live write test (roadmap P0.8 and P8.5, needs the maintainer's explicit go)

Goal: prove, on one real pump, that a write works, is read back and can be undone — and answer
the open questions of P0.8: what does the cloud answer to a write, how long until the read-back
matches, what happens to a rejected value.

**Rule:** nothing is written until the maintainer says "go" for this test in the current session.
Everything below is the plan, not a licence.

## Choice of change

Raise the *heating curve* of the main circuit and of circuit 1 by **1 °C** (the smallest step the
cloud allows), observe, then put it back. Raising is the safe direction (the house gets slightly
more heat, never less), and a one-degree step is within the normal range of daily use.
Prefer daytime and mild weather.

## Before

1. Note the current value of both curves in the Thermia app **and** in Home Assistant (they must
   agree).
2. Take a read-only baseline of every register: `python scripts/live_smoke.py > before.txt`
   (needs `THERMIA_USERNAME` / `THERMIA_PASSWORD` in the environment).
3. Make sure the pump shows *online* and the integration has debug logging for
   `custom_components.thermia_cloud` (the dev instance does).

## Steps

| # | Action | Expected |
|---|---|---|
| 0 | Turn **Read-only mode ON**, then try to change the main curve | Error "Read-only mode is on", **no** request in the log. This tests the kill switch without touching the pump |
| 1 | Try an impossible value with the action `thermia_cloud.set_register` (e.g. 99) | Rejected locally ("Value rejected …"), no request |
| 2 | Turn Read-only mode **OFF**. Set the main-circuit curve to *current + 1* (Developer tools → Actions → `number.set_value`, exact value, not the slider) | No error. The entity keeps the old value and shows `pending_value`; within ~30 s the value changes and `pending_value` disappears. Log (debug): the cloud's answer and *"read back … after N s"* |
| 3 | Check the Thermia app | Shows the new value |
| 4 | Wait 2 minutes, run `live_smoke.py > after.txt`, `diff before.txt after.txt` | Only the changed register differs (plus values that change on their own, e.g. temperatures) |
| 5 | Set the curve back to the original value | Same behaviour as step 2 |
| 6 | Repeat steps 2–5 for **circuit 1** | Same; the main curve must **not** move when circuit 1 is changed (they are separate registers) |

## Automation comes after, not instead

Do the manual run first: a failure in an automation is much harder to read. Once steps 2–6 are
clean, the "both curves +1" convenience is a tiny script (two sequential `number.set_value`
calls, main then circuit 1), roadmap P8.6.

## Pass / fail

Pass: every step behaves as expected, the pump ends at the original values, and the log shows the
read-back time. Fail or doubt at any step: stop, set the original values back (in the app if
needed), turn Read-only mode on, and record what happened in `API-NOTES.md`.

## What to record afterwards

Cloud response to a write (status and body), time to read-back, anything surprising → update
`API-NOTES.md` (§3, §8), tick P0.8 and P8.5 in the roadmap.
