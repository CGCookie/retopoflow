# Contours Help ![](contours_32.png width:32px;height:32px;padding:0px)

The Contours tool gives you a quick and easy way to retopologize cylindrical forms.
For example, it's ideal for organic forms, such as arms, legs, tentacles, tails, horns, etc.

The tool works by drawing strokes perpendicular to the form to define the contour of the shape.
Each additional stroke drawn will either extrude the current selection or cut a new loop into the edges drawn over.

You may draw strokes in any order, from any direction.

![](help_contours.png)


## Drawing

|  |  |  |
| --- | --- | --- |
| `Action+Drag` | : | slide selected loop |
| `Action+Double` | : | select loop |
| `Action` | : | slide selected loop |
| `Select` <br> `Shift+Select` | : | select edge |
| `Ctrl+Select` <br> `Ctrl+Shift+Select` | : | select loop |
| `Ctrl+Action` | : | draw contour stroke perpendicular to form. newly created contour extends selection if applicable. |
| `A` | : | deselect / select all |
| `F` <br> `Enter` | : | Bridge selected edge loops |

## Transform

|  |  |  |
| --- | --- | --- |
| `G` | : | slide |
| `R` | : | rotate loop in plane |
| `Shift+R`<br>`R+Double` | : | rotate loop in screen |

## Other

|  |  |  |
| --- | --- | --- |
| `X` <br> `Delete` <br> `Backspace` | : | delete/dissolve selected |
| `Shift+Up` <br> `Shift+Down` | : | increase / decrease segment counts |
| `Equals` <br> `Minus` | : | increase / decrease segment counts |

## Tips

- Extrude Contours from an existing edge loop by selecting it first.
- Contours works with symmetry, enabling you to contour torsos and other symmetrical objects!
