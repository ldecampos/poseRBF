# Drive joints

A driven transform gets the blended move of the poses through its
`offsetParentMatrix`. Its own channels stay free.

1. Put the joint, or any transform, where it has to be at rest.
2. Select it and click **Add Selected Transforms** in the **Driven** tab. Every pose
    starts with it at rest.

## Pose it by hand

1. Right-click the pose and click **Go To Pose**.
2. Move, rotate or scale the joint by its channels.
3. Right-click the pose and click **Update Driven**. The channels go back to rest and
    the joint stays where it was.

## Pose it by numbers

Type in the **Driven** table. The numbers are the move from rest: translation, rotation
in degrees and scale.

## A joint that already had an offset

The value its `offsetParentMatrix` had is kept and multiplied in. If it was already
connected, the joint cannot be driven, and the message says so.

## Stop driving it

Right-click the header of one of its columns and click **Remove**. It goes back to its
rest.
