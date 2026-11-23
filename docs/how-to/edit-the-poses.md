# Edit the poses

Right-click a pose in the **Poses** or the **Driven** tab.

| Action            | What it does                                                         |
| ----------------- | -------------------------------------------------------------------- |
| **Add Pose**      | Adds a pose where the drivers are, with what the driven show now     |
| **Go To Pose**    | Puts the drivers where they were when the pose was taken             |
| **Update Pose**   | Moves the pose to where the drivers are; what it asks for is kept    |
| **Update Driven** | Stores in the pose where the driven transforms are; the rest is kept |
| **Rename**        | Edits its name; a double click on the name does too                  |
| **Delete**        | Removes the pose; the last one cannot be removed                     |

The selected pose is the same in both tabs.

## Two poses in the same place

With **Regularization** at 0, two poses cannot have the same driver values: an RBF could
not tell them apart. The message names both, and nothing changes.

## Undo

Every edit is one undo step. Creating an RBF is not undone: **Delete** removes it and
returns what it drove to rest.
