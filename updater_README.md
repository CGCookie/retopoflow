Addon Updater
==========

This python module is created to provide an autoamted and easy way to implement auto-update checking and installing inside of blender addons for code that is hosted on github

(Readme is a work in progress)


### Features
 - Intelligently compare addon version against version numbers on github and 
 - Easily adjust segments per contour segment
 - Guide Mode: quickly generate whole sections of contour cuts in a single stroke

## Usage
The python module acts as a singleton, the module is treated as the class object itself and its data is shared across all files that import it. Setting an attribute in one file will persist in other files of the same addon. 

Example:

*__init__.py*

bash```
from .addon_updater import Updater as myUpdater

# ... 

def register():
	# ...
	myUpdater.user = "GithubUsername"
	myUpdater.repo = "GithubRepository"
	myUpdater.current_version = bl_info["version"] # the current addon version from bl_info
```

*someOperatorClass.py*
bash```
from .addon_updater import Updater as myUpdater

#...

def execute(self):
	(update_ready, version, link) = myUpdater.check_for_update()
	updater.run_update(force=False) # only runs if update_ready = true


# ... 



