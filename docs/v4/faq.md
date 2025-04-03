# Retopoflow FAQ

Below are answers to some common questions about Retopoflow.

## Where is the Retopoflow menu?

There is no longer a separate mode in Retopoflow 4, so there is no need for a menu in the 3D View header. Instead, you can find the tools in the Edit Mode toolbar. To quickly start a new retopology session, use one of the Retopology options added to the Object Mode Add Mesh menu.

## I cannot create new geometry!  Help!?

All of the tools that create new geometry do so while holding `Ctrl`. See the tools or [Retopoflow Mode](/v4/general.html) for more actions.

## Why is my geometry below the source mesh?

Sometimes, when the source mesh contains objects that are very thin, overlap, or nearly overlap, Retopoflow will snap geometry to the inner surface.
To fix this, use the Cleanup operation in the tool settings to push the vertices out along their normal before snapping them back to the source surface.

## Why can't I see the mirror modifier while I'm working?

Blender's Retopology overlay does not currently support viewing modifiers in Edit Mode unless you turn on the On Cage option, which is represented by the triangle mesh data icon.

## Is there a polycount limit?

Retopoflow 4 can comfortably work at the high resolutions needed for modern 3D graphics. The performance varies by tool. For example, PolyPen can work perfectly smoothly on meshes as high as 50 million polygons while Contours will have a few second delay at polycounts that high since it walks every face. We are currently working on alternative algorithms for any area that can be slow, even at extreme polycounts, so that you never have to worry about that again.


