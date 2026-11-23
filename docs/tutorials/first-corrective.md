# Tutorial: a first corrective

An elbow corrective: when the elbow bends, a corrective joint moves to keep the
volume of the inner elbow. It needs poseRBF installed (see the
[README](https://github.com/ldecampos/poseRBF#installation)) and an arm with a
skinned mesh.

1. Click **poseRBF** on the shelf.
2. Select the elbow joint, type `elbowRBF` as the name and click **New from
    Selection**. The first pose, `rest`, is the scene as it is.
3. Create a corrective joint near the inner elbow, add it to the skin and give it
    weights around the elbow.
4. In the **Driven** tab, select the corrective joint and click **Add Selected
    Transforms**.
5. In the **Poses** tab, bend the elbow and click **Add Pose**.
6. Move the corrective joint until the elbow looks right. Right-click the new pose
    and click **Update Driven**. The joint's channels return to rest, and the joint
    stays in place through the RBF.
7. Bend the elbow back and forth: the corrective follows.
