# ![](contours-icon.png) Contours Help

Shortcut: {{contours tool}}

The Contours tool gives you a quick and easy way to retopologize cylindrical forms.
For example, it's ideal for organic forms, such as arms, legs, tentacles, tails, horns, etc.

The tool works by drawing strokes perpendicular to the form to define the contour of the shape.
Each additional stroke drawn will either extrude the current selection or cut a new loop into the edges drawn over.

You may draw strokes in any order, from any direction.

![](help_contours.png)


## Creating

|  |  |  |
| --- | --- | --- |
| {{insert}}                           | : | draw contour stroke perpendicular to form. newly created contour extends selection if applicable. |
| {{increase count}}                   | : | increase segment counts in selected loop |
| {{decrease count}}                   | : | decrease segment counts in selected loop |
| {{fill}}                             | : | bridge selected edge loops |


## Selecting

|  |  |  |
| --- | --- | --- |
| {{select single, select single add}} | : | select edge |
| {{select smart, select smart add}}   | : | smart select loop |
| {{select paint, select paint add}}   | : | paint edge selection |
| {{select path add}}                  | : | select edges along shortest path |
| {{select all}}                       | : | select / deselect all |
| {{deselect all}}                     | : | deselect all |

## Transforming

|  |  |  |
| --- | --- | --- |
| {{action}}           | : | grab and slide selected geometry under mouse |
| {{grab}}             | : | slide selected loop |
| {{rotate plane}}     | : | rotate selected loop in plane |
| {{rotate screen}}    | : | rotate selected loop in screen |
| {{smooth edge flow}} | : | smooths edge flow of selected geometry |

## Other

|  |  |  |
| --- | --- | --- |
| {{delete}}         | : | delete/dissolve/collapse selected |

## Tips

- Extrude Contours from an existing edge loop by selecting it first.
- Contours works with symmetry, enabling you to contour torsos and other symmetrical objects!
