# Retopoflow Mode
In previous versions, Retopoflow tools were only accessable in a special mode that was completely separated from the rest of Blender. Since Retopoflow 4, these tools have been integrated tightly into Edit Mode. However, switching to one of the Retopoflow tools does still enter you into a type of mode that is specifically set up for retopology.

Entering a Retopoflow tool will adjust Blender's settings for:
- The selection mode
- Snapping
- Auto-merging vertices
- The retopology overlay
- Fading inactive geometry
- Object wireframes (for seeing the result of modifiers)

Switching out of a Retopoflow tool will restore all of your previous settings. You can enable or disable any of these automatic behaviors in Retopoflow's preferences.

## Terminology

| :--- | :--- | :--- |
| Source Object(s) | : | The original object(s) that you are re-creating.  These meshes typically have a high polygon count with poor topology and edge flow (ex: result of Dyntopo in Sculpt Mode) |
| Retopology Object    | : | The new object that stores the retopologized surface.  This mesh typically has a low polygon count with good topology and edge flow. |

You must have at least one source object to draw on for the Retopoflow tools to function.

Any mesh object that is visible and not the active retopolgoy object is considered a source object.
This means that you can hide or move objects to different scenes to change which source objects will be retopologized.

You can also mark objects as non-selectable in the Outliner and in Retopoflow's Options menu (far right in the tool header) choose Exclude Non-Selectable to keep those objects visible but not acting as sources.

## Selection

Selection in Retopoflow tools follows Blender's selection paradigm as much as possible.

The main difference is when using the brush-based tools like Tweak and Relax. In those, selection cannot be done with `LMB` (left mouse button) because that action is already used to apply the brush. Instead, you can use other Blender hotkeys like `Shift LMB` to toggle select, `B` to box select, or `Ctrl RMB drag` to lasso select.

Also, since `Ctrl LMB` is already used for creating new geometry in the other tools, Blender's Pick Shortest Path operator is not accessable with that hotkey. However, you can still use `Shift Ctrl LMB` to the same effect.

The tools in Retopoflow can be used in any selection mode, but are generally more useful in some than others. For example, PolyPen expects to connect to edges and verts but not faces, so switching to PolyPen enables both edge and vert selection and disables face selection by default. All tools have a preferred selection mode that is set automatically when switching to the tool.

*Tip: In Blender, you can always enable multiple selection modes by holding* `Shift` *while choosing them.*

Blender's default shortcut for loop selection is `Alt Left Click` or `Double Click` depending on your preferences. In Retopoflow, you can always use both!

## Altered Operators

Retopoflow has slightly altered versions of a few Blender operators in order to make them more useful for retopology.

- **Translate** (`G`) has been modified slighly to improve snapping behavior, but you should not need to think about this and can use it just like Blender's Translate.

## Common Settings

All settings for the Retopoflow tools can be found in the 3D View tool header, the sidebar in the Tool tab, or the Tool tab of the Properties Editor when the tool is active in the 3D View toolbar.

The insert tools share the same **Tweak** settings for how big the selection hitbox is, whether vertices are auto-merged, and how big the auto-merge threshold is while using `LMB Drag` on geometry to tweak it. *These settings are not the same as the Tweak Brush tool settings.*

Brush tools have the same **Brush** settings, though they are not shared across the tools. That way, you can use a small Tweak brush with a large Relax brush if you prefer.

- **Radius** controls the size of the brush and can be adjusted with the hotkey `F`
- **Strength** controls how much the brush effects the geometry and can be adjusted with the hotkey `Shift F`
- **Falloff** controls how much the strength of the brush is feathered near the edges and can be adjusted with the hotkey `Ctrl F`

## General Options

The far right side of the tool settings in any Retopoflow tool is the General Options dropdown. In it, you can:

- Choose to exclude non-selectable objects from being a snapping source
    - This is the same as Blender's option of the same name in the Snapping settings
- Adjust the retopology overlay's color and offset distance
- Adjust how much non-active objects are faded
- Choose to expand or collapse the Retopoflow tools in the toolbar
- Choose to expand or collapse the masking options in the tool header for the brush tools

If you are seeing the retopology object through the source object, decrease the retopology offset distance.

## Switching Tools

You can quickly switch between Retopoflow tools and access some of their common settings by using the Retopoflow pie menu. It is currently mapped to the hotkey `W` while a Retopoflow tool is active.