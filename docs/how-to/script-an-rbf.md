# Script an RBF

Every action of the window is a function of `poserbf.commands`, one undo step
each.

```python
from maya import cmds
from poserbf import commands

rbf = commands.create("twistRBF", ["hand_l"], transforms=["lowerarm_twist_l"])
commands.set_driver(rbf, "hand_l", rotation=0.0, twist=1.0, axis="x")
for pose, angle in (("in", 90.0), ("out", -90.0)):
    cmds.setAttr("hand_l.rotateX", angle)
    commands.add_pose(rbf, pose)
    commands.set_pose_move(rbf, pose, "lowerarm_twist_l", rotate=(angle / 2, 0, 0))
commands.go_to_pose(rbf, "rest")
commands.set_options(rbf, kernel="cubic", margin=0.01)
```

- `update_driven` stores what a driven transform shows; `set_pose_move` sets the
    move from rest by numbers; `update_pose` moves a pose to the drivers' state.
- `definition_of` returns everything stored about an RBF.
- `delete` removes an RBF and returns what it drove to rest.

Every function: [reference](../reference/index.md).
