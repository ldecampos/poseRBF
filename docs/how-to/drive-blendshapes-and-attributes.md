# Drive blendShapes and attributes

**One target per pose.** Connect the board's `weights[i]` to the target of pose
*i*. In interpolative mode a weight is exactly 1 at its pose and 0 at the others.

**Several targets or attributes per pose:**

1. Select the blendShape node and select its targets, or any attributes, in the
    Channel Box.
2. In the **Driven** tab, click **Add Channel Box Attributes**. Their current
    values become their rest.
3. In the **Driven** table, type the value each pose asks for.

Far from every pose, they return to rest.

From Python:

```python
from poserbf import commands

commands.add_driven("elbowRBF", values=["elbowFix.bend"])
commands.set_pose_values("elbowRBF", "bent", [1.0])
```
