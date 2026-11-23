# A first script, for developers

The elbow of [A first corrective](first-corrective.md), made and read from Python. It
needs poseRBF [installed](../how-to/install.md) and the arm of that tutorial's first
step, in a scene with nothing else.

## 1. Create the RBF

Run in the Script Editor, in a Python tab:

```python
from maya import cmds
from poserbf import commands

rbf = commands.create("elbowRBF", ["elbow"], transforms=["elbow_fix"])
print(rbf, commands.weights(rbf))
```

It prints `elbowRBF (1.0,)`. The RBF has one pose, `rest`, and the elbow is at it.

## 2. Say how the driver is compared

```python
commands.set_driver(rbf, "elbow", rotation=0.0, swing=1.0, axis="x")
```

The elbow is compared by where its X axis points.

## 3. Add the pose

```python
cmds.setAttr("elbow.rotateZ", 120)
commands.add_pose(rbf, "bent")
commands.set_pose_move(rbf, "bent", "elbow_fix", translate=(0.75, -0.85, 0.0))
commands.go_to_pose(rbf, "rest")
```

The move is measured from rest, so the numbers are how far the joint travels.

## 4. Read it back

```python
for angle in (0, 60, 120):
    cmds.setAttr("elbow.rotateZ", angle)
    print(angle, [round(weight, 2) for weight in commands.weights(rbf)])
```

It prints:

```text
0 [1.0, 0.0]
60 [0.5, 0.5]
120 [0.0, 1.0]
```

## Next

- [Script an RBF](../how-to/script-an-rbf.md): read, change and delete.
- Every function: {doc}`commands <../reference/api/poserbf/commands/index>`.
