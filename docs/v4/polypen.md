# ![](/images/icons/polypen-icon.png) PolyPen

![](/images/polypen.jpg)

The PolyPen tool provides absolute control for creating complex topology on a vertex-by-vertex basis (e.g., low-poly game models).
This tool lets you insert vertices, extrude edges, fill faces, and transform the subsequent geometry all within one tool and in just a few clicks.

## Inserting
<!--
| :--- | :--- | :--- |
| {{ site.data.keymaps.insert }} | : | insert geometry connected to selected geometry |
-->
To create a new vertex using PolyPen, make sure no other retopology geometry is selected and hold `Ctrl` and `LMB` (Left Mouse Click) on the surface of the source geometry.

To follow this guide, keep the **Insert Method** set to **Tri / Quad** for now.

To create an edge, keep just that new vertex selected and `Ctrl LMB` on another part of the surface.

To create a triangle, keep that edge selected or select any other edge and `Ctrl LMB` again.

To turn a triangle into a quad, select it and `Ctrl LMB` one more time to define the fourth corner.

With the **Tri / Quad** method, you can quickly and explicitly define all four corners of a quad and it is the most precise way to work.

However, sometimes you'll want to quickly insert quads in one click. For that, switch the **Insert Method** over to **Quad**. You could also choose **Triangle** to not automatically convert triangles into quads, **Edge** to not create any faces, or **Vertex** to only create vertices that are not connected to anything.

PolyPen can also be used to fill a quad between two edges. To fill in **Tri / Quad** or **Quad** mode, just select one edge, hold `Ctrl` and `LMB` on the second edge. Done! Keep in mind that you can also use Blender's `F` hotkey with any vert or face selected to create a new face with the next closest two vertices.


## Cutting

PolyPen can also be used as a simple knife. To make a cut, hold `Ctrl` and either hover over a selected edge if there is a selection, or any edge if there is no selection. `LMB` on the edge and then `LMB` on any edge that is connected to the same face.

PolyPen's knife cannot currently cut through multiple edges at the same time, cannot cut in the middle of a face, and does not have alignment guides like Blender's knife. We plan to improve the knife functionalty going forward but in the meantime, for more advanced features, it is recommended to use Blender's knife with the hotkey `K` and then use Retopoflow's [Mesh Cleanup operator](mesh_cleanup.html) on the result to snap the new vertices to the surface of the source object.

## Selecting

The default selection mode for PolyPen is Vertex + Edge so that you can quickly tweak both vertices and edges. However, you can work in just Vertex mode if you find yourself accidentally selecting edges.


## Transforming

A `LMB Drag` on components in PolyPen will perform a tweak action similar to Blender's Tweak tool. The tweaking settings are shared across multiple tools and can be read about on the [Retopoflow Mode](general.html) docs page under Common Settings.