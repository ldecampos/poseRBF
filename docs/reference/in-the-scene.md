# In the scene

An RBF called `elbowRBF` is made of:

| Node                        | Type           | What it holds                                          |
| --------------------------- | -------------- | ------------------------------------------------------ |
| `elbowRBF`                  | `bifrostBoard` | The graph, its constants and its ports                 |
| `elbowRBF_setup`            | `network`      | Its definition, as JSON                                |
| `<transform>_poseRBFOffset` | `multMatrix`   | Only for a driven transform that already had an offset |

## Ports of the board

| Port       | Type              | What it is                                        |
| ---------- | ----------------- | ------------------------------------------------- |
| `drivers`  | array of matrices | The `.matrix` of each transform driver, in order  |
| `numbers`  | array of doubles  | Each number driver, in order                      |
| `weights`  | array of doubles  | The weight of each pose, in order                 |
| `values`   | array of doubles  | Each driven attribute, in order                   |
| `matrices` | array of matrices | The `offsetParentMatrix` of each driven transform |

## Attributes of the network node

| Attribute           | What it holds                                                      |
| ------------------- | ------------------------------------------------------------------ |
| `poseRBFDefinition` | Drivers, poses, driven and options; the source of truth            |
| `poseRBFBoard`      | The link to the board                                              |
| `poseRBFWeights`    | A copy of every weight, so that any of them can be read on its own |
