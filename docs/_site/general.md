# RetopoFlow Mode
In previous versions, RetopoFlow tools were only accessable in a special mode that was completely seperated from the rest of Blender. Since RetopoFlow 4, these tools have been integrated tightly into Edit Mode. However, switching to one of the RetopoFlow tools does still enter you into a type of mode that is specifically set up for retopology.

Entering a RetopoFlow tool will adjust Blender's settings for:
- The selection mode
- The retopology overlay
- Snapping
- Auto-merging Vertices
- Showing object origins

Switching out of a RetopoFlow tool will restore all of your previous settings.

## Terminology

| :--- | :--- | :--- |
| Source Object(s) | : | The original object(s) that you are re-creating.  These meshes typically have a high polygon count with poor topology and edge flow (ex: result of Dyntopo in Sculpt Mode) |
| Retopology Object    | : | The new object that stores the retopologized surface.  This mesh typically has a low polygon count with good topology and edge flow. |

Any mesh object that is visible and not the active retopolgoy object is considered a source object.
This means that you can hide or move objects to different scenes to change which source objects will be retopologized.

## Selection

Selection in RetopoFlow tools follows Blender's selection paradigm as much as possible.

The main difference is when using the brush-based tools like Tweak and Relax. In those, selection cannot be done with `LMB` (left mouse button) because that action is already used to apply the brush. Instead, you can use other Blender hotkeys like `Shift LMB` to toggle select, `B` to box select, or `Ctrl RMB drag` to lasso select.

Also, since `Ctrl LMB` is already used for creating new geometry in the other tools, Blender's Pick Shortest Path operator is not accessable with that hotkey. However, you can still use `Shift Ctrl LMB` to the same effect.

The tools in RetopoFlow can be used in any selection mode, but are generally more useful in some than others. For example, PolyPen expects to connect to edges and verts but not faces, so switching to PolyPen enables both edge and vert selection and disables face selection. All tools have a preferred selection mode that is set automatically when switching to the tool.

## Altered Operators

RetopoFlow has slightly altered versions of a few Blender operators in order to make them more useful for retopology.

- Translate (`G`) has been modified slighly to improve snapping behavior, but you should not need to think about this and can use it just like Blender's Translate.

## Common Settings

The insert tools share the same **Tweak** settings for how big the selection hitbox is, whether vertices are auto-merged, and how big the auto-merge threshold is while using `Left Mouse Drag` on geometry to tweak it. These settings are not the same as the Tweak Brush tool settings.

Brush tools have the same **Brush** settings, though they are not shared across the tools. That way, you can use a small Tweak brush with a large Relax brush if you prefer.

- **Radius** controls the size of the brush and can be adjusted with the hotkey `F`
- **Strength** controls how much the brush effects the geometry and can be adjusted with the hotkey `Shift F`
- **Falloff** controls how much the strength of the brush is feathered near the edges and can be adjusted with the hotkey `Ctrl F`
