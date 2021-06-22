# ![](tweak-icon.png) Tweak Help

Shortcut: {{ site.data.keymaps.tweak_tool }}

Quick Shortcut: {{ site.data.keymaps.tweak_quick }}


The Tweak tool allows you to easily adjust vertex positions with a brush.

![](help_tweak.png)

## Transforming


| :--- | :--- | :--- |
| {{ site.data.keymaps.brush }}          | : | tweak all vertices within brush |
| {{ site.data.keymaps.brush_alt }}      | : | tweak only selected vertices within brush |

## Changing Brush Options


| :--- | :--- | :--- |
| {{ site.data.keymaps.brush_radius }}   | : | adjust brush size |
| {{ site.data.keymaps.brush_strength }} | : | adjust brush strength |
| {{ site.data.keymaps.brush_falloff }}  | : | adjust brush falloff |

These options can also be stored as presets in the Brush Options panel. 

To quickly switch between presets, use the {{ site.data.keymaps.pie_menu_alt0 }} pie menu. 

## Masking

Tweak has several options to control which vertices are or are not moved.
Each option is below, along with setting and description.

### Boundary


| :--- | :--- | :--- |
| Exclude  | : | Tweak vertices not along boundary |
| Slide    | : | Tweak vertices along boundary, but move them by sliding along boundary |
| Include  | : | Tweak all vertices within brush, regardless of being along boundary |

### Symmetry


| :--- | :--- | :--- |
| Exclude  | : | Tweak vertices not along symmetry plane |
| Slide    | : | Tweak vertices along symmetry plane, but move them by sliding along symmetry plane |
| Include  | : | Tweak all vertices within brush, regardless of being along symmetry plane |

### Hidden


| :--- | :--- | :--- |
| Exclude  | : | Tweak only visible vertices |
| Include  | : | Tweak all vertices within brush, regardless of visibility |

### Selected


| :--- | :--- | :--- |
| Exclude  | : | Tweak only unselected vertices |
| Only     | : | Tweak only selected vertices |
| All      | : | Tweak all vertices within brush, regardless of selection |

