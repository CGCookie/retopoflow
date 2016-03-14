"""
Development goal timeline:
First get list of all tags from api
Then compare local tag or version? e.g. with a text file,
or make an option to assume the addon version number = the
tag number always (and if false, tries to makea  temp file
which holds the version number, or not even temp file but just
checks/compares against when doing an update check ..
eg check against the blende r__init__ file..? or addon itself
verison file to compare.


# current status
- [x] get list of tags
- [ ] get pretend comparison string/tuple (as if loaded in addon, but now just CMI)
- [ ] download update (into another folder for now)
- [ ] GitHub: check for when we are getting too many request per hour (60?)
--  > it gets blocked, so detec that specific html error/response


# ULTIMATE OPTIONS:
- Using releases or tags for checking (there is code for most recent release, not tag)
-- for releases: browser_download_url, https://developer.github.com/v3/repos/releases/#get-a-single-release-asset
-- for tags: parse list of tags, e.g. https://api.github.com/repos/cgcookie/retopoflow/tags
- file_path comparison: a saved file location to use/check for
-- Used to check when the last check was, e.g. if not updating every single time run
- Release number format option, e.g. v{0}.{1}.{2}, to know how to search for numbers
- Source code location, ie from the zip, or if there are any additional included files
- Option to pull from current master instead of release?
- List of files or directories to not overwrite/remove on update
-- Useful for things like local preference files, etc.
-- Could be overwritten with a full "clean install" option to entirely refresh the folder

"""

#############################################################################
# here test benching the actual module we are writing

print("----------- testing module")
import addon_updater

print("----------- creating instance")
my_updater = addon_updater.Updater("cgcookie","helloworld",use_releases=False)
# my_updater = addon_updater.Updater("cgcookie","retopoflow",use_releases=False)
print("Initial updater: ",my_updater)
my_updater.user = "cgcookie"
my_updater.repo = "retopoflow"
print("updated values: ",my_updater)


print("----------- testing get tags")
# this will autoamtically call the api and populate tags/latest tag
# errors are not entirely graceful yet
tags = my_updater.tags 
print(tags)

print("----------- testing get most recent tags")
print(my_updater.tag_latest) # already should have it local since we called tags,
# but if we hadn't called tags first this would also end up being an api call

print("----------- test version comparison")
my_updater.current_version = (1,1,2) #tuple format, would get from bpy's addon version
(update_ready, version, link) = my_updater.check_for_update() # returns (true, version#0 if one ready
print("New version ready? ",update_ready)
print("New version number? ",version, " versus current version: ",my_updater.current_version)
print("(Currently only checks if different, not if one greater than another)")

print("----------- test getting a local copy of repo")
my_updater.stage_repository(link) # improvements still to be made
# at the moment, just downloads as zip, doesnt' extract just yet

