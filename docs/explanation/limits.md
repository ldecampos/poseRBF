# Limits

- **Parallel evaluation with the interface open.** Bifrost boards, poseRBF's and any
    other, can stall for tens to hundreds of milliseconds per frame. Serial evaluation
    does not; with Cached Playback on, played frames come from the cache.
- **Notes in the Graph Editor.** On a board created in the session, backdrops and notes
    show after the scene is saved and reopened.
- **Half a turn.** Twist is measured from 0 to 180 degrees either way, and a pose that
    moves a driven transform more than half a turn from rest is ambiguous.
- **Edits by hand.** Constants changed in the graph are overwritten by the next edit of
    the tool.
- **Cycles.** An RBF cannot drive what drives it. The connection is refused, and the
    message names the cycle.
