# Welcome to RetopoFlow!

RetopoFlow is a suite of Blender tools that automatically generate geometry which snaps to your source objects as you draw on the surface. 

The tools work because of our custom "Retopology Mode", which gets more information about the objects you're drawing on than Blender can give in Edit Mode. It also alows us to display the polygons in a cleaner, more helful style. 

<label class="not-online"><input type="checkbox" checked="BoundBool('''options['welcome']''')">Show this Welcome note when RetopoFlow starts</label>

![feature](images/retopoflow_3_feature.png)

## Getting Started

Check out our [quick start guide](quick_start.html) or our [video tutorials](https://cgcookie.com/courses/retopology-with-retopoflow-3) to learn the basics of using RetopoFlow.

RetopoFlow also has a full documentation and help system within the app.

You can find it in the Help section of the toolbar or, at any time, press {{site.data.keymaps.general_help}} to open the [general help document](general.html), {{site.data.keymaps.all_help}} to open the [table of contents](table_of_contents.html), or {{site.data.keymaps.tool_help}} to open the help documents for the currently selected tool.


## Find an issue? Please let us know!

Whenever you see a bug, please let us know so that we can fix it!

Be sure to submit screen shots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button in the toolbar.
We have added buttons to error messages that open the issue tracker in your default browser and save screen shots of Blender.


## Feedback

Our small team works hard at making RetopoFlow the best retopology tool you can find. We want to know how RetopoFlow has benefited you in your work! Please consider doing the following:

- Purchase a copy of RetopoFlow on the [Blender Market](https://blendermarket.com/products/retopoflow) to help fund future developments.
- Give us a [rating](https://blendermarket.com/products/retopoflow/ratings#new_product_rating) with comments on the Blender Market. (requires purchasing a copy through Blender Market)
- Follow our development on [Twitter](https://twitter.com/RetopoFlow).
- Consider [donating](https://paypal.me/gfxcoder/) to our drink funds :)


## Known Issues / Future Work

Below is a list of known issues that we are currently working on.

- RF causes Blender to crash on a small number of machines.
- UI can take about a split second to register hovering or clicking.
- UI wrapping is not quite correct.
- Patches supports only basic fills.
- Starting RF with large source or target meshes can be slow.
- RF actions are not tied into Blender keymaps.
- RF does not allow execution of other add-ons, pie menus, Blender operators, etc.
- RF does not work correctly with more than one 3D View.
- Some non-mesh objects and some modifiers do not work well with RetopoFlow.
    - Non-mesh objects appear to scale too big or too small
    - Modifiers cause output to appear incorrect


## Final Words

We thank you for using RetopoFlow, and we look forward to hearing back from you!

Cheers!

<br>
---The CG Cookie Tool Development Team
