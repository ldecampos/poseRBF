# Use several drivers

For a result that appears only when several joints are posed together, such as an
arm raised and an elbow bent:

1. Select both joints and click **New from Selection**. A driver added later, with
    **Add Selected Transforms** in the **Drivers** tab, takes its current state in
    every existing pose.
2. In the **Drivers** tab, set how each driver is measured: swing for a shoulder,
    rotation for an elbow.
3. Add a pose for each driver alone, with the result at rest, and a pose for both
    together, with the result wanted.

Factors weigh drivers against each other. With rotation in degrees and translation
in centimetres, a translation factor of 10 makes 1 cm count as 10 degrees.

From Python:

```python
from poserbf import commands

rbf = commands.create("flexRBF", ["upperarm_l", "lowerarm_l"], values=["flex.biceps"])
commands.set_driver(rbf, "upperarm_l", rotation=0.0, swing=1.0, axis="x")
```
