# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####


"""
See documentation for usage
https://github.com/CGCookie/blender-addon-updater

"""

import urllib.request
import urllib
import os
import json
import zipfile
import shutil
import asyncio # for async processing
import threading
import time
from datetime import datetime,timedelta

# blender imports, used in limited cases
import bpy
import addon_utils

# -----------------------------------------------------------------------------
# Define error messages/notices & hard coded globals
# -----------------------------------------------------------------------------

DEFAULT_API_URL = "https://api.github.com" # plausibly could be some other system
DEFAULT_TIMEOUT = 10
DEFAULT_PER_PAGE = 30


# -----------------------------------------------------------------------------
# The main class
# -----------------------------------------------------------------------------

class Singleton_updater(object):
	"""
	This is the singleton class to reference a copy from, 
	it is the shared module level class
	"""
	
	def __init__(self):
		"""
		#UPDATE
		:param user: string # name of the user owning the repository
		:param repo: string # name of the repository
		:param api_url: string # should just be the github api link
		:param timeout: integer # request timeout
		:param current_version: tuple # typically 3 values meaning the version #
		"""

		self._user = None
		self._repo = None
		self._website = None
		self._api_url = DEFAULT_API_URL
		self._current_version = None
		self._tags = []
		self._tag_latest = None
		self._tag_names = []
		self._latest_release = None
		self._include_master = False
		self._manual_only = False
		self._version_min_update = None
		self._version_max_update = None

		# by default, backup current addon if new is being loaded
		self._backup_current = True 

		# by default, enable/disable the addon.. but less safe.
		self._auto_reload_post_update = False

		self._check_interval_enable = False
		self._check_interval_months = 0
		self._check_interval_days = 7
		self._check_interval_hours = 0
		self._check_interval_minutes = 0

		# runtime variables, initial conditions
		self._verbose = False
		self._fake_install = False
		self._async_checking = False # only true when async daemon started
		self._update_ready = None
		self._update_link = None
		self._update_version = None
		self._source_zip = None
		self._check_thread = None
		self._skip_tag = None

		# get from module data
		self._addon = __package__.lower()
		self._addon_package = __package__ # must not change
		self._updater_path = os.path.join(os.path.dirname(__file__),
							self._addon+"_updater")
		self._addon_root = os.path.dirname(__file__)
		self._json = {}
		self._error = None
		self._error_msg = None
		self._prefiltered_tag_count = 0

		# to verify a valid import, in place of placeholder import
		self.invalidupdater = False


	# -------------------------------------------------------------------------
	# Getters and setters
	# -------------------------------------------------------------------------

	@property
	def addon(self):
		return self._addon
	@addon.setter
	def addon(self, value):
		self._addon = str(value)

	@property
	def verbose(self):
		return self._verbose
	@verbose.setter
	def verbose(self, value):
		try:
			self._verbose = bool(value)
			if self._verbose == True:
				print(self._addon+" updater verbose is enabled")
		except:
			raise ValueError("Verbose must be a boolean value")

	@property
	def include_master(self):
		return self._include_master
	@include_master.setter
	def include_master(self, value):
		try:
			self._include_master = bool(value)
		except:
			raise ValueError("include_master must be a boolean value")

	@property
	def manual_only(self):
		return self._manual_only
	@manual_only.setter
	def manual_only(self, value):
		try:
			self._manual_only = bool(value)
		except:
			raise ValueError("manual_only must be a boolean value")

	@property
	def auto_reload_post_update(self):
		return self._auto_reload_post_update
	@auto_reload_post_update.setter
	def auto_reload_post_update(self, value):
		try:
			self._auto_reload_post_update = bool(value)
		except:
			raise ValueError("Must be a boolean value")

	@property
	def fake_install(self):
		return self._fake_install
	@fake_install.setter
	def fake_install(self, value):
		if type(value) != type(False):
			raise ValueError("fake_install must be a boolean value")
		self._fake_install = bool(value)
			
	@property
	def user(self):
		return self._user
	@user.setter
	def user(self, value):
		try:
			self._user = str(value)
		except:
			raise ValueError("User must be a string value")

	@property
	def json(self):
		if self._json == {}:
			self.set_updater_json()
		return self._json

	@property
	def repo(self):
		return self._repo
	@repo.setter
	def repo(self, value):
		try:
			self._repo = str(value)
		except:
			raise ValueError("User must be a string")

	@property
	def website(self):
		return self._website
	@website.setter
	def website(self, value):
		if self.check_is_url(value) == False:
			raise ValueError("Not a valid URL: " + value)
		self._website = value

	@property
	def async_checking(self):
		return self._async_checking

	@property
	def api_url(self):
		return self._api_url
	@api_url.setter
	def api_url(self, value):
		if self.check_is_url(value) == False:
			raise ValueError("Not a valid URL: " + value)
		self._api_url = value

	@property
	def stage_path(self):
		return self._updater_path
	@stage_path.setter
	def stage_path(self, value):
		if value == None:
			if self._verbose:print("Aborting assigning stage_path, it's null")
			return
		elif value != None and not os.path.exists(value):
			try:
				os.makedirs(value)
			except:
				if self._verbose:print("Error trying to staging path")
				return
			# definitely check for errors here, user issues
		self._updater_path = value


	@property
	def tags(self):
		if self._tags == []:
			return []
		tag_names = []
		for tag in self._tags:
			tag_names.append(tag["name"])

		return tag_names

	@property
	def tag_latest(self):
		if self._tag_latest == None:
			return None
		return self._tag_latest["name"]

	@property
	def latest_release(self):
		if self._releases_latest == None:
			return None
		return self._latest_release

	@property
	def current_version(self):
		return self._current_version

	@property
	def update_ready(self):
		return self._update_ready

	@property
	def update_version(self):
		return self._update_version

	@property
	def update_link(self):
		return self._update_link

	@current_version.setter
	def current_version(self,tuple_values):
		if type(tuple_values) is not tuple:
			raise ValueError(\
			"Not a tuple! current_version must be a tuple of integers")
		for i in tuple_values:
			if type(i) is not int:
				raise ValueError(\
				"Not an integer! current_version must be a tuple of integers")
		self._current_version = tuple_values

	def set_check_interval(self,enable=False,months=0,days=14,hours=0,minutes=0):
		# enabled = False, default initially will not check against frequency
		# if enabled, default is then 2 weeks

		if type(enable) is not bool:
			raise ValueError("Enable must be a boolean value")
		if type(months) is not int:
			raise ValueError("Months must be an integer value")
		if type(days) is not int:
			raise ValueError("Days must be an integer value")
		if type(hours) is not int:
			raise ValueError("Hours must be an integer value")
		if type(minutes) is not int:
			raise ValueError("Minutes must be an integer value")

		if enable==False:
			self._check_interval_enable = False
		else:
			self._check_interval_enable = True
		
		self._check_interval_months = months
		self._check_interval_days = days
		self._check_interval_hours = hours
		self._check_interval_minutes = minutes

	@property
	def check_interval(self):
		return (self._check_interval_enable,
				self._check_interval_months,
				self._check_interval_days,
				self._check_interval_hours,
				self._check_interval_minutes)

	@property
	def error(self):
		return self._error

	@property
	def error_msg(self):
		return self._error_msg

	@property
	def version_min_update(self):
		return self._version_min_update
	@version_min_update.setter
	def version_min_update(self, value):
		if value == None:
			self._version_min_update = None
			return
		if type(value) != type((1,2,3)):
			raise ValueError("Version minimum must be a tuple")
		else:
			# potentially check entries are integers
			self._version_min_update = value


	@property
	def version_max_update(self):
		return self._version_max_update
	@version_max_update.setter
	def version_max_update(self, value):
		if value == None:
			self._version_max_update = None
			return
		if type(value) != type((1,2,3)):
			raise ValueError("Version maximum must be a tuple")
		else:
			# potentially check entries are integers
			self._version_max_update = value



	# -------------------------------------------------------------------------
	# Parameter validation related functions
	# -------------------------------------------------------------------------


	def check_is_url(self,url):
		if not ("http://" in url or "https://" in url):
			return False
		if "." not in url:
			return False
		return True

	def get_tag_names(self):
		tag_names = []
		self.get_tags(self)
		for tag in self._tags:
			tag_names.append(tag["name"])
		return tag_names

	# declare how the class gets printed

	def __repr__(self):
		return "<Module updater from {a}>".format(a=__file__)

	def __str__(self):
		return "Updater, with user: {a}, repository: {b}, url: {c}".format(
						a=self._user,
						b=self._repo, c=self.form_repo_url())


	# -------------------------------------------------------------------------
	# API-related functions
	# -------------------------------------------------------------------------

	def form_repo_url(self):
		return self._api_url+"/repos/"+self.user+"/"+self.repo


	def get_tags(self):
		request = "/repos/"+self.user+"/"+self.repo+"/tags"
		if self.verbose:print("Getting tags from server")

		# get all tags, internet call
		all_tags = self.get_api(request)
		self._prefiltered_tag_count = len(all_tags)

		# pre-process to skip tags
		if self.skip_tag != None:
			self._tags = [tg for tg in all_tags if self.skip_tag(tg)==False]
		else:
			self._tags = all_tags

		# get master too, if needed, and place in front but not actively
		if self._include_master == True:
			request = self._api_url +"/repos/" \
					+self.user+"/"+self.repo+"/zipball/master"
			master = {
				"name":"Master",
				"zipball_url":request
			}
			self._tags = [master] + self._tags # append to front

		if self._tags == None:
			# some error occured
			self._tag_latest = None
			self._tags = []
			return
		elif self._prefiltered_tag_count == 0 and self._include_master == False:
			self._tag_latest = None
			self._error = "No releases found"
			self._error_msg = "No releases or tags found on this repository"
			if self.verbose:print("No releases or tags found on this repository")
		elif self._prefiltered_tag_count == 0 and self._include_master == True:
			self._tag_latest = self._tags[0]
			if self.verbose:print("Only master branch found:",self._tags[0])
		elif len(self._tags) == 0 and self._prefiltered_tag_count > 0:
			self._tag_latest = None
			self._error = "No releases available"
			self._error_msg = "No versions found within compatible version range"
			if self.verbose:print("No versions found within compatible version range")
		else:
			self._tag_latest = self._tags[0]
			if self.verbose:print("Most recent tag found:",self._tags[0])


	# all API calls to base url
	def get_api_raw(self, url):
		request = urllib.request.Request(self._api_url + url)
		try:
			result = urllib.request.urlopen(request)
		except urllib.error.HTTPError as e:
			self._error = "HTTP error"
			self._error_msg = str(e.code)
			self._update_ready = None 
		except urllib.error.URLError as e:
			self._error = "URL error, check internet connection"
			self._error_msg = str(e.reason)
			self._update_ready = None 
			return None
		else:
			result_string = result.read()
			result.close()
			return result_string.decode()
		# if we didn't get here, return or raise something else
		
		
	# result of all api calls, decoded into json format
	def get_api(self, url):
		# return the json version
		get = None
		get = self.get_api_raw(url) # this can fail by self-created error raising
		if get != None:
			return json.JSONDecoder().decode( get )
		else:
			return None


	# create a working directory and download the new files
	def stage_repository(self, url):

		# first make/clear the staging folder
		# ensure the folder is always "clean"
		local = os.path.join(self._updater_path,"update_staging")
		error = None

		if self._verbose:print("Preparing staging folder for download:\n",local)
		if os.path.isdir(local) == True:
			try:
				shutil.rmtree(local) 
				os.makedirs(local)
			except:
				error = "failed to remove existing staging directory"
		else:
			try:
				os.makedirs(local)
			except:
				error = "failed to make staging directory"
		
		if error != None:
			if self._verbose: print("Error: Aborting update, "+error)
			raise ValueError("Aborting update, "+error)

		if self._backup_current==True:
			self.create_backup()
		if self._verbose:print("Now retrieving the new source zip")

		self._source_zip = os.path.join(local,"source.zip")
		
		if self._verbose:print("Starting download update zip")
		urllib.request.urlretrieve(url, self._source_zip)
		if self._verbose:print("Successfully downloaded update zip")

	def create_backup(self):
		if self._verbose:print("Backing up current addon folder")
		local = os.path.join(self._updater_path,"backup")
		tempdest = os.path.join(self._addon_root,
						os.pardir,
						self._addon+"_updater_backup_temp")

		if os.path.isdir(local) == True:
			shutil.rmtree(local)
		if self._verbose:print("Backup destination path: ",local)

		# make the copy
		shutil.copytree(self._addon_root,tempdest)
		shutil.move(tempdest,local)

		# save the date for future ref
		now = datetime.now()
		self._json["backup_date"] = "{m}-{d}-{yr}".format(
				m=now.strftime("%B"),d=now.day,yr=now.year)
		self.save_updater_json()

	def restore_backup(self):
		if self._verbose:print("Restoring backup")

		if self._verbose:print("Backing up current addon folder")
		backuploc = os.path.join(self._updater_path,"backup")
		tempdest = os.path.join(self._addon_root,
						os.pardir,
						self._addon+"_updater_backup_temp")
		tempdest = os.path.abspath(tempdest)

		# make the copy
		shutil.move(backuploc,tempdest)
		shutil.rmtree(self._addon_root)
		os.rename(tempdest,self._addon_root)

		self._json["backup_date"] = ""
		self._json["just_restored"] = True
		self._json["just_updated"] = True
		self.save_updater_json() 

		self.reload_addon()

	def upack_staged_zip(self):

		if os.path.isfile(self._source_zip) == False:
			if self._verbose:print("Error, update zip not found")
			return -1

		# clear the existing source folder in case previous files remain
		try:
			shutil.rmtree( os.path.join(self._updater_path,"source") )
			os.makedirs( os.path.join(self._updater_path,"source") )
			if self._verbose:print("Source folder cleared and recreated")
		except:
			pass
		

		if self.verbose:print("Begin extracting source")
		if zipfile.is_zipfile(self._source_zip):
			with zipfile.ZipFile(self._source_zip) as zf:
				# extractall is no longer a security hazard
				zf.extractall(os.path.join(self._updater_path,"source"))
		else:
			if self._verbose:
				print("Not a zip file, future add support for just .py files")
			raise ValueError("Resulting file is not a zip")
		if self.verbose:print("Extracted source")

		# either directly in root of zip, or one folder level deep
		unpath = os.path.join(self._updater_path,"source")
		if os.path.isfile(os.path.join(unpath,"__init__.py")) == False:
			dirlist = os.listdir(unpath)
			if len(dirlist)>0:
				unpath = os.path.join(unpath,dirlist[0])

			if os.path.isfile(os.path.join(unpath,"__init__.py")) == False:
				if self._verbose:print("not a valid addon found")
				if self._verbose:print("Paths:")
				if self._verbose:print(dirlist)

				raise ValueError("__init__ file not found in new source")

		# now commence merging in the two locations:
		origpath = os.path.dirname(__file__) # verify, is __file__ always valid?

		self.deepMergeDirectory(origpath,unpath)
		
		# now save the json state
		#  Change to True, to trigger the handler on other side
		#  if allowing reloading within same blender instance
		self._json["just_updated"] = True
		self.save_updater_json()
		self.reload_addon()
		self._update_ready = False


	# merge folder 'merger' into folder 'base' without deleting existing
	def deepMergeDirectory(self,base,merger):
		if not os.path.exists(base):
			if self._verbose:print("Base path does not exist")
			return -1
		elif not os.path.exists(merger):
			if self._verbose:print("Merger path does not exist")
			return -1

		# this should have better error handling
		# and also avoid the addon dir
		# Could also do error handling outside this function
		for path, dirs, files in os.walk(merger):
			relPath = os.path.relpath(path, merger)
			destPath = os.path.join(base, relPath)
			if not os.path.exists(destPath):
				os.makedirs(destPath)
			for file in files:
				destFile = os.path.join(destPath, file)
				if os.path.isfile(destFile):
					os.remove(destFile)
				srcFile = os.path.join(path, file)
				os.rename(srcFile, destFile)
	

	def reload_addon(self):
		# if post_update false, skip this function
		# else, unload/reload addon & trigger popup
		if self._auto_reload_post_update == False:
			print("Restart blender to reload addon and complete update")
			return


		if self._verbose:print("Reloading addon...")
		addon_utils.modules(refresh=True)
		bpy.utils.refresh_script_paths()

		# not allowed in restricted context, such as register module
		# toggle to refresh
		bpy.ops.wm.addon_disable(module=self._addon_package)
		bpy.ops.wm.addon_refresh()
		bpy.ops.wm.addon_enable(module=self._addon_package)


	# -------------------------------------------------------------------------
	# Other non-api functions and setups
	# -------------------------------------------------------------------------

	def clear_state(self):
		self._update_ready = None
		self._update_link = None
		self._update_version = None
		self._source_zip = None
		self._error = None
		self._error_msg = None

	def version_tuple_from_text(self,text):

		if text == None: return ()

		# should go through string and remove all non-integers, 
		# and for any given break split into a different section

		segments = []
		tmp = ''
		for l in str(text):
			if l.isdigit()==False:
				if len(tmp)>0:
					segments.append(int(tmp))
					tmp = ''
			else:
				tmp+=l
		if len(tmp)>0:
			segments.append(int(tmp))

		if len(segments)==0:
			if self._verbose:print("No version strings found text: ",text)
			if self._include_master == False:
				return ()
			else:
				return ('master')
		return tuple(segments)

	# called for running check in a background thread
	def check_for_update_async(self, callback=None):

		if self._json != None and "update_ready" in self._json:
			if self._json["update_ready"] == True:
				self._update_ready = True
				self._update_link = self._json["version_text"]["link"]
				self._update_version = str(self._json["version_text"]["version"])
				# cached update
				callback(True)
				return

		# do the check
		if self._check_interval_enable == False:
			return
		elif self._async_checking == True:
			if self._verbose:print("Skipping async check, already started")
			return # already running the bg thread
		elif self._update_ready == None:
			self.start_async_check_update(False, callback)

	def check_for_update_now(self, callback=None):

		self._error = None
		self._error_msg = None

		if self._verbose:
			print("Check update pressed, first getting current status")
		if self._async_checking == True:
			if self._verbose:print("Skipping async check, already started")
			return # already running the bg thread
		elif self._update_ready == None:
			self.start_async_check_update(True, callback)
		else:
			self._update_ready = None
			self.start_async_check_update(True, callback)


	# this function is not async, will always return in sequential fashion
	# but should have a parent which calls it in another thread
	def check_for_update(self, now=False):
		if self._verbose:print("Checking for update function")

		# clear the errors if any
		self._error = None
		self._error_msg = None

		# avoid running again in, just return past result if found
		# but if force now check, then still do it
		if self._update_ready != None and now == False:
			return (self._update_ready,self._update_version,self._update_link)

		if self._current_version == None:
			raise ValueError("current_version not yet defined")
		if self._repo == None:
			raise ValueError("repo not yet defined")
		if self._user == None:
			raise ValueError("username not yet defined")

		self.set_updater_json() # self._json

		if now == False and self.past_interval_timestamp()==False:
			if self.verbose:
				print("Aborting check for updated, check interval not reached")
			return (False, None, None)
		
		# check if using tags or releases
		# note that if called the first time, this will pull tags from online
		if self._fake_install == True:
			if self._verbose:
				print("fake_install = True, setting fake version as ready")
			self._update_ready = True
			self._update_version = "(999,999,999)"
			self._update_link = "http://127.0.0.1"
			
			return (self._update_ready, self._update_version, self._update_link)
		
		# primary internet call
		self.get_tags() # sets self._tags and self._tag_latest

		self._json["last_check"] = str(datetime.now())
		self.save_updater_json()


		# if (len(self._tags) == 0 and self._include_master == False) or\
		# 		(len(self._tags) < 2 and self._include_master == True):
		# 	if self._verbose:print("No tag found on this repository")
		# 	self._update_ready = False
		# 	self._error = "No online versions found"
		# 	if self._include_master == True:
		# 		self._error_msg = "Try installing master from Reinstall"
		# 	else:
		# 		self._error_msg = "No repository tags found for version comparison"
		# 	return (False, None, None)

		# can be () or ('master') in addition to version tag
		new_version = self.version_tuple_from_text(self.tag_latest)

		if len(self._tags)==0:
			self._update_ready = False
			self._update_version = None
			self._update_link = None
			return (False, None, None)
		elif self._include_master == False:
			link = self._tags[0]["zipball_url"] # potentially other sources
		else:
			link = self._tags[1]["zipball_url"] # potentially other sources
		
		if new_version == ():
			self._update_ready = False
			self._update_version = None
			self._update_link = None
			return (False, None, None)
		elif str(new_version).lower() == "master":
			self._update_ready = True
			self._update_version = new_version
			self._update_link = link
			self.save_updater_json()
			return (True, new_version, link)
		elif new_version > self._current_version:
			self._update_ready = True
			self._update_version = new_version
			self._update_link = link
			self.save_updater_json()
			return (True, new_version, link)
		# elif new_version != self._current_version:
		# 	self._update_ready = False
		# 	self._update_version = new_version
		# 	self._update_link = link
		# 	self.save_updater_json()
		# 	return (True, new_version, link)

		# if no update, set ready to False from None
		self._update_ready = False
		self._update_version = None
		self._update_link = None
		return (False, None, None)

	def set_tag(self,name):
		tg = None
		for tag in self._tags:
			if name == tag["name"]:
				tg = tag
				break
		if tg == None:
			raise ValueError("Version tag not found: "+revert_tag)
		new_version = self.version_tuple_from_text(self.tag_latest)
		self._update_version = new_version
		self._update_link = tg["zipball_url"]


	def run_update(self,force=False,revert_tag=None,clean=False,callback=None):
		# revert_tag: could e.g. get from drop down list
		# different versions of the addon to revert back to
		# clean: not used, but in future could use to totally refresh addon
		self._json["update_ready"] = False
		self._json["ignore"] = False # clear ignore flag 
		self._json["version_text"] = {}

		if revert_tag != None:
			self.set_tag(revert_tag)
			self._update_ready = True

		# clear the errors if any
		self._error = None
		self._error_msg = None

		if self.verbose:print("Running update")

		if self._fake_install == True:
			# change to True, to trigger the reload/"update installed" handler
			if self._verbose:
				print("fake_install=True")
				print("Just reloading and running any trigger")
			self._json["just_updated"] = True
			self.save_updater_json()
			if self._backup_current == True:
				self.create_backup()
			self.reload_addon()
			self._update_ready = False

		elif force==False:
			if self._update_ready != True:
				if self.verbose:print("Update stopped, new version not ready")
				return 1 # stopped
			elif self._update_link == None:
				# this shouldn't happen if update is ready
				if self.verbose:print("Update stopped, update link unavailable")
				return 1 # stopped

			if self.verbose and revert_tag==None:
				print("Staging update")
			elif self.verbose:
				print("Staging install")
			self.stage_repository(self._update_link)
			self.upack_staged_zip()

		else:
			if self._update_link == None:
				return # stopped, no link - run check update first or set tag
			if self.verbose:print("Forcing update")
			# first do a check
			if self._update_link == None:
				if self.verbose:print("Update stopped, could not get link")
				return
			self.stage_repository(self._update_link)
			self.upack_staged_zip()
			# would need to compare against other versions held in tags

		# run the front-end's callback if provided
		if callback != None:callback()

		# return something meaningful, 0 means it worked
		return 0


	def past_interval_timestamp(self):
		if self._check_interval_enable == False:
			return True # ie this exact feature is disabled
		
		if "last_check" not in self._json or self._json["last_check"] == "":
			return True
		else:
			now = datetime.now()
			last_check = datetime.strptime(self._json["last_check"],
										"%Y-%m-%d %H:%M:%S.%f")
			next_check = last_check
			offset = timedelta(
				days=self._check_interval_days + 30*self._check_interval_months,
				hours=self._check_interval_hours,
				minutes=self._check_interval_minutes
				)

			delta = (now - offset) - last_check
			if delta.total_seconds() > 0:
				if self._verbose:
					print("Determined it's time to check for updates")
				return True
			else:
				if self._verbose:
					print("Determined it's not yet time to check for updates")
				return False


	def set_updater_json(self):
		if self._updater_path == None:
			raise ValueError("updater_path is not defined")
		elif os.path.isdir(self._updater_path) == False:
			os.makedirs(self._updater_path)

		jpath = os.path.join(self._updater_path,"updater_status.json")
		if os.path.isfile(jpath):
			with open(jpath) as data_file:
				self._json = json.load(data_file)
				if self._verbose:print("Read in json settings from file")
		else:
			# set data structure
			self._json = {
				"last_check":"",
				"backup_date":"",
				"update_ready":False,
				"ignore":False,
				"just_restored":False,
				"just_updated":False,
				"version_text":{}
			}
			self.save_updater_json()


	def save_updater_json(self):

		# first save the state
		if self._update_ready == True:
			self._json["update_ready"] = True
			self._json["version_text"]["link"]=self._update_link
			self._json["version_text"]["version"]=self._update_version
		else:
			self._json["update_ready"] = False
			self._json["version_text"] = {}

		jpath = os.path.join(self._updater_path,"updater_status.json")
		outf = open(jpath,'w')
		data_out = json.dumps(self._json,indent=4)
		outf.write(data_out)
		outf.close()
		if self._verbose:
			print(self._addon+": Wrote out updater json settings to file, with the contents:")
			print(self._json)

	def json_reset_postupdate(self):
		self._json["just_updated"] = False
		self._json["update_ready"] = False
		self._json["version_text"] = {}
		self.save_updater_json()
	def json_reset_restore(self):
		self._json["just_restored"] = False
		self._json["update_ready"] = False
		self._json["version_text"] = {}
		self.save_updater_json()
		self._update_ready = None # reset so you could check update again

	def ignore_update(self):
		self._json["ignore"] = True
		self.save_updater_json()

	# -------------------------------------------------------------------------
	# ASYNC stuff
	# -------------------------------------------------------------------------

	def start_async_check_update(self, now=False,callback=None):
		if self._async_checking == True:
			return
		if self._verbose: print("Starting background checking thread")
		check_thread = threading.Thread(target=self.async_check_update,
										args=(now,callback,))
		check_thread.daemon = True
		self._check_thread = check_thread
		check_thread.start()
		
		return True

	def async_check_update(self, now, callback=None):
		self._async_checking = True
		if self._verbose:print("BG: Checking for update now in background")
		# time.sleep(3) # to test background, in case internet too fast to tell
		# try:
		self.check_for_update(now=now)
		# except Exception as exception:
		# 	print("Checking for update error:")
		# 	print(exception)
		# 	self._update_ready = False
		# 	self._update_version = None
		# 	self._update_link = None
		# 	self._error = "Error occurred"
		# 	self._error_msg = "Encountered an error while checking for updates"

		if self._verbose:
			print("BG: Finished checking for update, doing callback")
		if callback != None:callback(self._update_ready)
		self._async_checking = False
		self._check_thread = None


	def stop_async_check_update(self):
		if self._check_thread != None:
			try:
				if self._verbose:print("Thread will end in normal course.")
				# however, "There is no direct kill method on a thread object."
				# better to let it run its course
				#self._check_thread.stop()
			except:
				pass
		self._async_checking = False
		self._error = None
		self._error_msg = None



# -----------------------------------------------------------------------------
# The module-shared class instance,
# should be what's imported to other files
# -----------------------------------------------------------------------------

Updater = Singleton_updater()

