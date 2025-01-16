# RetopoFlow FAQ

Below are answers to some common questions with RetopoFlow.

## Q: I cannot create new geometry!  Help!?

All of the tools that create new geometry do so using {{ site.data.keymaps.insert }} action.
Selection uses the {{ site.data.keymaps.select_single }} action.
See [General Help](general.md) for more actions.

## Q: Why is my geometry below the source mesh?

Sometimes, when the source mesh contains objects that are very thin, overlap, or nearly overlap, RetopoFlow will snap geometry to the inner surface.
To fix this, use the Cleanup operation in the tool settings to push the vertices out along their normal before snapping them back to the source surface.

## Q: Why can't I see the mirror modifier while I'm working?

Blender's Retopology overlay does not currently support viewing modifiers in Edit Mode unless you turn on the On Cage option, which is represented by the triangle mesh data icon.
