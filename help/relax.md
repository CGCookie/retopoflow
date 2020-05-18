# Relax Help ![](relax_32.png width:32px;height:32px;padding:0px)

Shortcut: {{relax tool}}


The Relax tool allows you to easily relax the vertex positions using a brush.

![](help_relax.png)

## Transforming

|  |  |  |
| --- | --- | --- |
| {{brush}}          | : | relax all vertices within brush |
| {{brush alt}}      | : | relax only selected vertices within brush |

## Changing Brush Options

|  |  |  |
| --- | --- | --- |
| {{brush radius}}   | : | adjust brush size |
| {{brush strength}} | : | adjust brush strength |
| {{brush falloff}}  | : | adjust brush falloff |

## Masking

Relax has several options to control which vertices are or are not moved.
Each option is below, along with setting and description.

### Boundary

|  |  |  |
| --- | --- | --- |
| Exclude  | : | Relax vertices not along boundary |
| Include  | : | Relax all vertices within brush, regardless of being along boundary |

### Symmetry

|  |  |  |
| --- | --- | --- |
| Exclude  | : | Relax vertices not along symmetry plane |
| Maintain | : | Relax vertices along symmetry plane, but keep them on symmetry plane |
| Include  | : | Relax all vertices within brush, regardless of being along symmetry plane |

### Hidden

|  |  |  |
| --- | --- | --- |
| Exclude  | : | Relax only visible vertices |
| Include  | : | Relax all vertices within brush, regardless of visibility |

### Selected

|  |  |  |
| --- | --- | --- |
| Exclude  | : | Relax only unselected vertices |
| Only     | : | Relax only selected vertices |
| All      | : | Relax all vertices within brush, regardless of selection |

