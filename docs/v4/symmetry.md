# Symmetry

Retopoflow 3 had a whole symmetry system that was really just the mirror modifier under the hood.

In Retopoflow 4, you have full access to the mirror modifier directly and do not need to do anything extra for that to work with the Retopoflow tools.

To make things easier, though, there is a Mirror section in the tool settings for quickly toggling mirror axes, adjusting the mirror modifier properties, or applying the mirror modifier.

There are a few ways that the mirror can be displayed:

- **None** does not display the result of the mirror at all.
- **Applied** uses the modifier's On Cage display option to show the mirrored geometry as real geometry. The benefit is that it allows you to see the mirror while using the retopology overlay. The downside is that it can be confusing because it appears that the geometry is real when it actually is not. You will be able to select components on the 'fake' side but any operation performed on them will appear backwards and centered around the opposite, 'real' side.
- **Wire** shows the result of the mirror as grease pencil strokes that are colored according to the axis. You can control the opacity, thickness, and distance from the mesh. Because it is displayed in real 3D space and cannot use the retopology overlay, it needs an offset in order to not overlap with the source geometry.
- **Solid** shows the result of the mirror as faces that are colored according to the axis. Similar to Wire, this option cannot use the retopology overlay and is displayed in real 3D space. Its offset is based on the offset of the retopology overlay, but you can reduce that if needed. Unchecking Displace Boundaries will snap the boundaries to the source mesh and unchecking Displace Connected will snap any geometry that is connected to the 'real' geometry to the source mesh.

It is important to note that, while the retopology overlay is enabled, Blender only shows the result of modifiers if you enable the On Cage (mesh triangle) option in the modifier's header. In all other cases it is highly recommended to work with this off.

Working with Blender's Edit Mode Symmetry is not yet supported, as unfortunately it is rather broken and many regular operations in Blender are not yet supported.