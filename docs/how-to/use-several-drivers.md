# Use several drivers

For a result that shows only when several joints are posed together, such as an arm
raised and an elbow bent.

1. Select the joints and click **New from Selection**. A driver added later, with
    **Add Selected Transforms** in the **Drivers** tab, takes its current state in
    every existing pose.
2. In the **Drivers** tab, set [what is compared](choose-what-is-compared.md) of each:
    swing for a shoulder, rotation for an elbow.
3. Add a pose for each driver alone, with the result at rest, and one for both
    together, with the result wanted. Without the first ones, the result also shows
    with a single driver.

## Balance them with a factor

Drivers with different units do not weigh the same. With a jaw that opens 30 degrees
and a smile from 0 to 1, a full smile is 1 away from its pose and an open jaw is 30: the
smile hardly counts, and the result pops instead of fading.

A factor on the smile puts both on one scale. With the jaw at 20 degrees and a full
smile, the corrective weighs:

| Factor of the smile | Weight of the corrective |
| ------------------- | ------------------------ |
| 1                   | 0.000                    |
| 30                  | 0.669                    |

Likewise, with rotation in degrees and translation in centimetres, a translation factor
of 10 makes 1 cm count as 10 degrees.

## From Python

```python
from poserbf import commands

rbf = commands.create("flexRBF", ["upperarm_l", "lowerarm_l"], values=["flex.biceps"])
commands.set_driver(rbf, "upperarm_l", rotation=0.0, swing=1.0, axis="x")
```
