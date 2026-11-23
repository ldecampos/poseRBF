# How poseRBF works

A pose RBF (radial basis function) blends results from examples: when the drivers
are at a pose, the result is what that pose asks for; between poses, a blend. It
measures how far the drivers are from each pose, turns the distances into one
weight per pose, and blends with those weights.

## Distance

A driver is a transform, read through its local `.matrix`, or a number. A transform
is compared with each pose by four measures, each with its own factor (0 turns it
off):

| Measure     | Compares                                               | Unit        |
| ----------- | ------------------------------------------------------ | ----------- |
| Rotation    | the whole orientation                                  | degrees     |
| Swing       | where the local axis points; twist about it is ignored | degrees     |
| Twist       | the rotation about the local axis                      | degrees     |
| Translation | the position                                           | scene units |

A number is compared by its difference. The distance to a pose is the square root
of the sum of every factor-scaled measure, squared. Factors put different units on
one scale and give a driver more or less weight.

Several drivers make one pose out of several joints, such as an arm raised and an
elbow bent at the same time.

## Weight

The distance over the radius goes through a falloff curve: Gaussian, exponential,
linear, cubic or quintic. The radius is set, or automatic: 1.5 times the mean
distance from each pose to its nearest one.

- **Interpolative** mode solves the poses against each other, so each pose weighs
    exactly 1 at itself and 0 at the others. **Regularization** trades that
    exactness for smoothness when close poses ask for different results.
- **Additive** mode uses the falloffs as they are.

Negative weights can be set to 0. **Normalize** divides the weights by their sum:
always, only when the sum passes 1 (**Above One**, the default), or never.

## Results

- **Weights:** one per pose.
- **Values:** numbers each pose asks for, such as blendShape weights or any
    attribute. The result is rest plus the weighted sum of each pose's change from
    rest, so far from every pose a value returns to rest.
- **Transforms:** per pose, the move of a driven transform from its rest,
    blended from the identity and sent to the transform's `offsetParentMatrix`.
    Rotations blend as quaternions.

## The graph

Each RBF is one Bifrost board with the same graph. Only the drivers enter through
ports; the poses, the solved table and the options are constants, written by the
tool.

```text
drivers ─► matrix_distances ─┐
                             ├─► all_squared ─► pose_falloff ─► pose_weights ─► weights
numbers ─► number_distances ─┘                                      │
                                   values   ◄── driven_values ◄─────┤
                                   matrices ◄── driven_transforms ◄─┘
```

Every block carries a note in the Bifrost Graph Editor.

## Undo

Creating an RBF is not undone; deleting it removes it. Every edit is one undo step
of Maya's own.

## Limits

- With Maya's interface open and parallel evaluation, Bifrost boards, poseRBF's
    and any other, can stall for tens to hundreds of milliseconds per frame. Serial
    evaluation does not; with Cached Playback on, played frames come from the
    cache.
- On a board created in the session, backdrops and notes show in the Graph Editor
    after the scene is saved and reopened.
