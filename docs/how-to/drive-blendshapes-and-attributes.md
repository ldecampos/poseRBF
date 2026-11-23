# Drive blendShapes and attributes

## One target per pose

Connect the weight of the pose to the target. The weights are the board's `weights`, in
the order of the **Poses** tab: `elbowRBF.weights[1]` is the second one.

In interpolative mode a weight is exactly 1 at its pose and 0 at the others.

## Several targets or attributes per pose

1. Select the blendShape node, or any node, and its targets or attributes in the
    Channel Box.
2. In the **Driven** tab, click **Add Channel Box Attributes**. Their current values
    are their rest.
3. In the **Driven** table, type the value each pose asks for.

Far from every pose, they return to rest.

## From Python

```python
from poserbf import commands

commands.add_driven("elbowRBF", values=["elbowFix.bend"])
commands.set_pose_values("elbowRBF", "bent", [1.0])
```
