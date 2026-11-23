# Script an RBF, for developers

Every action of the window is a function of `poserbf.commands`, and each edit is one
undo step.

## Create and pose

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

- `update_driven` stores what a driven transform shows; `set_pose_move` sets the move
    from rest by numbers; `update_pose` moves a pose to the drivers' state.
- A driver is named after its plug; `hand_l.twist` becomes `hand_l_twist`.

## Read

```python
for rbf in commands.all_rbfs():
    definition = commands.definition_of(rbf)
    print(rbf, [pose.name for pose in definition.poses], definition.options.kernel)
    print(commands.weights(rbf))
```

`definition_of` returns everything stored about an RBF.

## Change many at once

```python
for rbf in commands.all_rbfs():
    commands.set_options(rbf, normalize="always")
```

## Handle what it refuses

An edit that cannot be built raises `ValueError` and changes nothing: two poses in the
same place, an attribute already connected, a driver that the RBF itself drives.

```python
try:
    commands.add_driven(rbf, values=["hand_l.rotateX"])
except ValueError as reason:
    print(reason)
```

## Delete

```python
commands.delete(rbf)
```

What it drove goes back to rest.

Every function: {doc}`commands <../reference/api/poserbf/commands/index>`.
