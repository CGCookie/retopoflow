# Welcome to RetopoFlow {[rf version]}!

Welcome to the latest version of RetopoFlow!

RetopoFlow is an add-on for Blender that brings together a set of retopology tools within a custom Blender mode to enable you to work more quickly, efficiently, and in a more artist-friendly manner.
The RF tools, which are specifically designed for retopology, create a complete workflow in Blender without the need for additional software.

The RetopoFlow tools automatically generate geometry by drawing on an existing surface, snapping the new mesh to the source surface at all times, meaning you never have to worry about your mesh conforming to the original model---no Shrinkwrap modifier required!
Additionally, all mesh generation is quad-based (except for PolyPen).

<input type="checkbox" value="options['welcome']">Show this Welcome note when RetopoFlow starts</input>


## Help

We have created help documents to describe the major parts of RetopoFlow.

At any time, press {{general help}} to open the [general help document](general.md), {{all help}} to open the [table of contents](table_of_contents.md), or {{tool help}} to open the help documents for the currently selected tool.


## Version 3.0 Notes

In RetopoFlow&nbsp;2.x, we completely rewrote the framework so that RF acts like any other Blender mode (like Edit Mode, Sculpt Mode, Vertex Paint Mode).
Choosing one of the tools from the RetopoFlow panel will start RetopoFlow Mode with the chosen tool selected.

Although the underlying framework has changed significantly, RetopoFlow&nbsp;3.x uses a similar workflow to RetopoFlow&nbsp;2.x.

When RetopoFlow Mode is enabled, all parts of Blender outside the 3D view will be darkened (and disabled) and windows will be added to the 3D view.
These windows allow you to switch between RF tools, set tool options, and get more information.
Also, this one-time Welcome message will greet you.

See our [change list](changelist.md) to see details about the changes mode since RetopoFlow&nbsp;2.x.


## Reporting Bugs

Whenever you see a bug, please let us know so that we can fix them!
Be sure to submit screen shots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting [GitHub Issues](https://github.com/CGCookie/retopoflow/issues).
We have added buttons to open the issue tracker in your default browser and to save screen shots of Blender.

![Global exception handling.](global_exception.png max-height:500px)


## Feedback

We have worked hard to make this as production-ready as possible.
We focused on stability and bug handling in addition to new features, improving overall speed, and making RetopoFlow easier to use.

We want to know how RetopoFlow has benefited you in your work.
Please consider doing the following:

- Purchase a copy of RetopoFlow on the [Blender Market](https://blendermarket.com/products/retopoflow) to help fund future developments.
- Give us a [rating](https://blendermarket.com/products/retopoflow/ratings) with comments on the Blender Market. (requires purchasing a copy through Blender Market)
- Follow our development on [Twitter](https://twitter.com/RetopoFlow_Dev).
- Consider [donating](https://paypal.me/gfxcoder/) to our drink funds :)


## Known Issues / Future Work

Below is a list of known issues that we are currently working on.

- Patches supports only rudimentary fills.
- Starting RF with large source or target meshes can be slow.
- The updater is temporarily disabled for this release.
- RF actions are not tied into Blender keymaps.
- RF does not allow execution of other add-ons, pie menus, Blender operators, etc.
- RF does not work correctly with more than one 3D Views.
- UI can take about a half second to register hovering or clicking.


## Final Words

We thank you for using RetopoFlow, and we look forward to hearing back from you!

Cheers!

<br>
---The CG Cookie Tool Development Team


<input type="checkbox" value="options['welcome']">Show this Welcome note when RetopoFlow starts</input>
