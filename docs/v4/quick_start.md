# Quick Start Guide

This guide will help you get started with RetopoFlow {{ site.data.options.rf_version }}.

## The Short, Short Version

To start retopologizing in Blender after installing Retopoflow:

1. Have an object you want to draw new topology on top of
2. Go to Add > Mesh in Object mode
3. Either click "Retopology at Cursor" or "Retopology at Active"

    - "at Cursor" will create a new retopology object located at the 3D Cursor and oriented to the world.
    - "at Active" will create a new retopology object located at and oriented to the active object.

All of the Retopoflow tools require some other object in the scene that the new geometry can snap to. You can also create a new retopology object yourself or select an existing retopology object, enter Edit Mode on it, and switch to any of the RetopoFlow tools in the toolbar.

If you are seeing the retopology mesh through the source object, decrease the retopology overlay's offset distance in either Blender's Edit Mode Overlays popover or Retopoflow's General options.


Enjoy!

*For a more in-depth explanation of how Retopoflow works, read the [Retopoflow Mode](/v4/general.html) page.*