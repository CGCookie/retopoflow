# Welcome to RetopoFlow 3.0.0β2!

Welcome to the latest version of RetopoFlow!

RetopoFlow is an add-on for Blender that brings together a set of retopology tools within a custom Blender mode to enable you to work more quickly, efficiently, and in a more artist-friendly manner.
The RF tools, which are specifically designed for retopology, create a complete workflow in Blender without the need for additional software.

The RetopoFlow tools automatically generate geometry by drawing on an existing surface, snapping the new mesh to the source surface at all times, meaning you never have to worry about your mesh conforming to the original model---no Shrinkwrap modifier required!
Additionally, all mesh generation is quad-based (except for PolyPen).

<input type="checkbox" value="options['welcome']">Show this Welcome note when RetopoFlow starts</input>



## Version 3.0 Notes

Below are a few notes about the current version of RetopoFlow.


### Change List

Below is a short list of major changes from RetopoFlow&nbsp;2.x.

- Left-mouse select is now a thing!
- Mouse dragging, clicking, and double-clicking are now possible actions.
- Some of the keymaps for some tools have changed to allow for LMB-select.
- The target mesh is what you are currently editing (Edit Mode), and the source meshes are any other visible mesh.
- Some RF tools have improved options.


### Blender versions

As of 2020 May 19, RetopoFlow has been tested to work well with Blender&nbsp;2.80--2.90α.
RF does have a few visual issues with Blender&nbsp;2.83β and 2.90α that we are currently working on, but RF _should_ work.

Note: This version will *not* work in Blender&nbsp;2.79b or earlier.


### New Framework

Due to some significant changes in the Blender 2.80 Python API, we had to rewrite a few key parts of RetopoFlow, specifically the rendering and UI.
Rather than keeping these updates only for RetopoFlow users, we decided to build the changes into a new framework called [CookieCutter](https://github.com/CGCookie/addon_common).
The CookieCutter framework has several brand new systems to handle states, UI drawing and interaction, debugging and exceptions, rendering, and much more.
CookieCutter was built from the ground up to be a maintainable, extensible, and configurable framework for Blender add-ons.

The new RetopoFlow sits on top of the CookieCutter framework, and we are excited to show off CookieCutter's features through RetopoFlow!

But with any unveiling on new things, there are new bugs and performance issues.
Our hope is that these problems will be much easier to fix in the new CookieCutter framework.
We will need your help, though.


### Reporting Bugs

Whenever you see a bug, please let us know so that we can fix them!
Be sure to submit screen shots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting [GitHub Issues](https://github.com/CGCookie/retopoflow/issues).
We have added buttons to open the issue tracker in your default browser and to save screen shots of Blender.

![Global exception handling.](global_exception.png max-height:500px)


### Feedback

We have worked hard to make this as production-ready as possible.
We focused on stability and bug handling in addition to new features, improving overall speed, and making RetopoFlow easier to use.

We want to know how RetopoFlow has benefited you in your work.
Please consider doing the following:

- Purchase a copy of RetopoFlow on the [Blender Market](https://blendermarket.com/products/retopoflow) to help fund future developments.
- Give us a [rating](https://blendermarket.com/products/retopoflow/ratings) with comments on the Blender Market. (requires purchasing a copy through Blender Market)
- Follow our development on [Twitter](https://twitter.com/RetopoFlow_Dev).
- Consider [donating](https://paypal.me/gfxcoder/) to our drink funds :)


### Known Issues / Future Work

Below is a list of known issues that we are currently working on.

- Patches supports only rudimentary fills.
- Starting RF with large source or target meshes can be slow.
- The updater is temporarily disabled for this release.
- RF actions are not tied into Blender keymaps.
- RF does not allow execution of other add-ons, pie menus, Blender operators, etc.
- RF does not work correctly with more than one 3D Views.


## Final Words

We thank you for using RetopoFlow, and we look forward to hearing back from you!

Cheers!

<br>
---The CG Cookie Tool Development Team


<input type="checkbox" value="options['welcome']">Show this Welcome note when RetopoFlow starts</input>
