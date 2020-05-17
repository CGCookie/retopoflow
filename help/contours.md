# Contours Help ![](contours_32.png width:32px;height:32px;padding:0px)

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
| {{select all}}                       | : | deselect / select all |

## Transforming

|  |  |  |
| --- | --- | --- |
| {{action}}        | : | grab and slide selected geometry under mouse |
| {{grab}}          | : | slide selected loop |
| {{rotate plane}}  | : | rotate selected loop in plane |
| {{rotate screen}} | : | rotate selected loop in screen |

## Other

|  |  |  |
| --- | --- | --- |
| {{delete}}         | : | delete/dissolve selected |

## Tips

- Extrude Contours from an existing edge loop by selecting it first.
- Contours works with symmetry, enabling you to contour torsos and other symmetrical objects!
