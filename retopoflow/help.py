'''
Copyright (C) 2018 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''


from ..config.options import retopoflow_version



# sync help texts with https://github.com/CGCookie/retopoflow-docs (http://docs.retopoflow.com/)

# https://wincent.com/wiki/Unicode_representations_of_modifier_keys

help_welcome = '''
# Welcome to RetopoFlow {version}!

RetopoFlow is an add-on for Blender that brings together a set of retopology tools within a custom Blender mode to enable you to work more quickly, efficiently, and in a more artist-friendly manner.
The RF tools, which are specifically designed for retopology, create a complete workflow in Blender without the need for additional software.

The RetopoFlow tools automatically generate geometry by drawing on an existing surface, snapping the new mesh to the source surface at all times, meaning you never have to worry about your mesh conforming to the original model---no Shrinkwrap modifier required!
Additionally, all mesh generation is quad-based (except for PolyPen).


## Changelog

Below is a summary of the changes made.
A full summary is available on [Blender Market](https://blendermarket.com/products/retopoflow).

### Major Changes from Version 2.x

- RetopoFlow 3.0 works in Blender 2.80!
- RF uses CG Cookie's CookieCutter framework
  - All new state handling
  - All new UI drawing


### Changes in 2.0.3

- Hiding RF buttons in 3D View panel to improve overall performance when Region Overlap is disabled
- Visualizing target geometry counts in bottom right corner
- Improved target rendering by constraining normal offset
- Only showing "small clip start" alert once per Blender run rather than once per RetopoFlow run
- By default, the options for unselected tools are hidden (can disable Options > General > Tool Options > Auto Hide Options).
- Overall stability improvements

### Minor Changes from Version 2.0.0

- Can navigate to all help documents through help system.
  (Click [All Help Documents](All Help Documents) button below or press `Shift+F1`)
- Fixed bug where navigation broke with internationalization settings
- Improved many UX/UI issues.
  For example, now the RetopoFlow panel will explicitly state whether a new target will be created and what meshes are acting as sources.
  For another example, RetopoFlow will now gracefully handle registration failures (usually happening when Blender is installed through package manager).
- Squashed many hard-to-find bugs in Loops, PolyPen, Patches, Strokes, Contours
- Better error handling with shader compilation.
- Fixed critical bug with framework.

### Major Changes from Version 1.x

What you see behind this message window is a complete rewrite of the code base.
RetopoFlow 2.x now works like any other Blender mode, like Edit Mode or Sculpt Mode, but it will also feel distinct.
We focused our 2.x development on two main items: stability and user experience.
With an established and solid framework, we will focus more on features in future releases.

- Everything runs within the RF Mode; no more separation of tools!
  In fact, the shortcut keys `Q`, `W`, `E`, `R`, `T`, `Y`, `U`, and `I` will switch quickly between the tools.
- Each tool has been simplified to perform its job well.
- All tools use the current selection for their context.
  For example, PolyStrips can edit any strip of quads by simply selecting them.
- The selected and active mesh is the Target Mesh, and any other visible meshes are Source Meshes.
- Many options and configurations are sticky, which means that some settings will remain even if you leave RF Mode or quit Blender.
- All tools have similar and consistent visualization, although they each will have their own custom widget (ex: circle cursor in Tweak) and annotations (ex: edge count in Contours).
- Mirroring (X, Y, and/or Z) is now visualized by overlaying a color on all the source meshes.
- Every change automatically commits to the target mesh; geometry is created in real-time!
  No more lost work from crashing.
- Auto saves will trigger!
- Undo and redo are universally available within RF Mode.
  Press `Ctrl+Z` roll back any change, or `Ctrl+Shift+Z` to redo.
- The new Strokes tool extends your target mesh with a simple selection and stroke.


## Feedback

We want to know how RetopoFlow has benefited you in your work.
Please consider doing the following:

- Give us a rating with comments on the Blender Market.
  (requires purchasing a copy through Blender Market)
- Purchase a copy of RetopoFlow on the Blender Market to help fund future developments.
- Consider donating to our drink funds :)

We have worked hard to make this as production-ready as possible.
We focused on stability and bug handling in addition to new features, improving overall speed, and making RetopoFlow easier to use.
However, if you find a bug or a missing feature, please let us know so that we can fix them!
Be sure to submit screenshots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting [https://github.com/CGCookie/retopoflow/issues](https://github.com/CGCookie/retopoflow/issues).
We have added buttons to open the issue tracker in your default browser and to save screenshots of Blender.

![](help_exception.png)


## Known Issues / Future Work

Below is a list of known issues that are currently being addressed.

- Source meshes with very high poly count can cause a delay and stutter at start-up time.
- A target mesh with high poly count target mesh can cause slowness in some tools.
- RF runs _very_ slowly (<1.0 FPS) on a few rare machines.
- Patches supports only rudimentary fills.
- RetopoFlow does not work with Blender 2.80 (beta).



## Final Words

We thank you for using RetopoFlow, and we look forward to hearing back from you!

Cheers!

<br>
---The CG Cookie Tool Development Team
'''.format(version=retopoflow_version)