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
Example base usage:

from addon_updater import Updater as myUpdater

myUpdater.repo = "repository_name"
myUpdater.user = "username"
myUpdater.stage_path = "//"
myUpdater.current_version = "v1.1.0"
myUpdater.set_check_interval(months=0,days=14,minutes=5) # optional


# Check for existing updates or any past versions
# option 1: backgorund, async check with callback function input
myUpdater.check_for_update_async(callback=None) # input callback function
# option 2: immediate, thread-blocking
(update_ready, version, link) = myUpdater.check_for_update()

# run the update
run_update(revert_tag=None)
# or, select a verion to install
tags = myUpdater.get_tag_names()
latest_tag = tags[0] # equivalent to using revert_tag = None
myUpdater.run_update(revert_tag=latest_tag) # e.g. latest_tag = "v1.0.0"


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
		:param use_releases: bool # else uses tags for release version checking
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
		self._releases = []
		self._latest_release = None
		self._backup_current = True # by default, backup current addon if new is being loaded
		self._auto_reload_post_update = False # by defautl, enable/disable the addon.. but less safe.
		 # "" # assume specific cachename, use addon?.cache
		self._check_interval_enable = False
		self._check_interval_months = 0
		self._check_interval_days = 14
		self._check_interval_hours = 0
		self._check_interval_minutes = 0

		# runtime variables, initial conditions
		self._verbose = False
		self._fake_install = False
		self._async_checking = False # only true when async daemon started
		self._update_ready = None
		self._connection_failed = False
		self._update_link = None
		self._update_version = None
		self._source_zip = None

		# get from module data
		self._addon = __package__
		self._addon_package = __package__ # must not change
		self._updater_path = os.path.join(os.path.dirname(__file__),
							self._addon+"_updater")
		self._addon_root = os.path.dirname(__file__)
		self._json = {}


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
			if self._verbose == True:print("Updater verbose is enabled")
		except:
			raise ValueError("Verbose must be a boolean value")

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
		return self._verbose
	@fake_install.setter
	def fake_install(self, value):
		if type(value) != type(False):
			raise ValueError("Verbose must be a boolean value")
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
	def connection_failed(self):
		return self._connection_failed

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
	def releases(self):
		if self._releases == []:
			return []
			# self._releases = self.get_releases()
		return self._releases

	@property
	def latest_release(self):
		if self._releases_latest == None:
			return None
			# ie we haven't parsed the server yet, do it now
			# self._releases = self.get_releases()
			# self._latest_release = self._releases[0]
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
			raise ValueError("Not a tuple! current_version must be a tuple of integers")
		for i in tuple_values:
			if type(i) is not int:
				raise ValueError("Not an integer! current_version must be a tuple of integers")
		self._current_version = tuple_values

	def set_check_interval(self,enable=False, months=0, days=14, hours=0, minutes=0):
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
			# if self._verbose:print("Auto-checking is disabled")
		else:
			self._check_interval_enable = True
			# if self._verbose:print("Auto-checking is enabled")

			# create conf file if not already present
		
		self._check_interval_months = months
		self._check_interval_days = days
		self._check_interval_hours = hours
		self._check_interval_minutes = minutes

		# if self._verbose:
		# 	print("Set interval check of: {x}months, {y}d {z}:{a}".format(
		# 			x=months,y=days,z=hours,a=minutes))

	@property
	def check_interval(self):
		return (self._check_interval_enable,
				self._check_interval_months,
				self._check_interval_days,
				self._check_interval_hours,
				self._check_interval_minutes)

	@user.setter
	def check_interval(self, value):
		raise ValueError("Check frequency is read-only")


	# -------------------------------------------------------------------------
	# Paramater validation related functions
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
		return "Updater, with user:{a}, repository:{b}, url:{c}".format(a=self._user,
									b=self._repo, c=self.form_repo_url())


	# -------------------------------------------------------------------------
	# API-related functions
	# -------------------------------------------------------------------------

	def form_repo_url(self):
		return self._api_url+"/repos/"+self.user+"/"+self.repo


	def get_tags(self):
		request = "/repos/"+self.user+"/"+self.repo+"/tags"
		# print("Request url: ",request)
		if self.verbose:print("Grabbing tags from server")

		# do more error checking e.g. no connection here, and relay back up
		self._tags = self.get_api(request)
		if len(self._tags) == 0:
			self._tag_latest = None
			if self.verbose:print("No tags found on this repositoru")
		else:
			self._tag_latest = self._tags[0]
			if self.verbose:print("Most recent tag found:",self._tags[0])


	# all API calls to base url
	def get_api_raw(self, url):
		request = urllib.request.Request(self._api_url + url)
		try:
			result = urllib.request.urlopen(request)
		except urllib.error.HTTPError as e:
			raise ValueError("HTTPError, code: ",e.code)
			# return or raise error?
		except urllib.error.URLError as e:
			raise ValueError("URLError, reason: ",e.reason)
			# return or raise error?
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
		return json.JSONDecoder().decode( get )


	# create a working directory and download the new files
	def stage_repository(self, url):

		# first make/clear the staging folder
		# ensure the folder is always "clean"
		local = os.path.join(self._updater_path,"update_staging")

		error = None

		# no, really should just remove eveyrthing but the cache if found
		# or use same as folder name but plus extension.. that could work
		if self._verbose:print("Preparing staging folder for download:\n",local)
		if os.path.isdir(local) == True:
			# improve try/except for permission errors or other OS errors
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

		if self._verbose:print("Todo: create backup zip of current addon now")
		if self._backup_current==True:
			self.create_backup()
		if self._verbose:print("Now retreiving the new source zip")

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
		if self._verbose:print("Backup temp path: ",tempdest)

		if self._verbose:print("Backup dest path: ",local)

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
		print(backuploc)
		print(tempdest)
		print(self._addon_root)

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
			print("Error, update zip not found")
			return -1

		# clear the existing source folder in case previous files remain
		try:
			shutil.rmtree( os.path.join(self._updater_path,"source") )
			os.makedirs( os.path.join(self._updater_path,"source") )
			print("Source folder cleared and recreated")
		except:
			pass
		


		if self.verbose:print("Begin extracting source")
		if zipfile.is_zipfile(self._source_zip):
			with zipfile.ZipFile(self._source_zip) as zf:
				# extractall is no longer a security hazard
				zf.extractall(os.path.join(self._updater_path,"source"))
		else:
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
				print("not a valid addon found")
				print("Paths:")
				print(dirlist)

				raise ValueError("__init__ file not found in new source")

		# now commence merging in the two locations:
		
		origpath = os.path.dirname(__file__) # CHECK that this is appropriate... not necessairly true..?
		#"/Users/patrickcrawford/Library/Application Support/Blender/2.76/scripts/addons/retopoflow/"
		print("Unstaging: unpath:",unpath,"  \nOrigpath:",origpath)


		self.deepMergeDirectory(origpath,unpath) ## SKIPPING THIS STEP FOR CHECKING
		# now save the json state

		# change to True, to trigger the handler on other side
		self._json["just_updated"] = True
		self.save_updater_json()
		self.reload_addon()
		self._update_ready = False


	# merge contents of folder 'merger' into folder 'base', without deleting existing
	def deepMergeDirectory(self,base,merger):
		if not os.path.exists(base):
			if self._verbose:print("Base path does not exist")
			return -1
		elif not os.path.exists(merger):
			if self._verbose:print("Merger path does not exist")
			return -1

		# this should have better error handling
		# and also avoid the addon dir
		# or do error handling outside this function?
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
		if self._auto_reload_post_update == False:
			print("Restart blender to reload")
			return



		if self._verbose:print("Reloading addon...")
		addon_utils.modules(refresh=True)
		bpy.utils.refresh_script_paths()

		# not allowed in restricted context, such as register module
		# toggle to refresh
		bpy.ops.wm.addon_disable(module=self._addon_package)

		bpy.ops.wm.addon_refresh()
		# consider removing cached files
		# __pycache__
		# try:
		# 	shutil//
		bpy.ops.wm.addon_enable(module=self._addon_package)



	# -------------------------------------------------------------------------
	# Other non-api functions and setups
	# -------------------------------------------------------------------------


	def version_tuple_from_text(self,text):

		# should go through string and remove all non-integers, 
		# and for any given break split into a different section

		segments = []
		tmp = ''
		for l in text:
			if l.isdigit()==False:
				if len(tmp)>0:
					segments.append(int(tmp)) # int(tmp)
					tmp = ''
			else:
				tmp+=l
		if len(tmp)>0:
			segments.append(int(tmp)) # int(tmp)

		if len(segments)==0:
			raise ValueError("Error in parsing version text")

		return tuple(segments) # turn into a tuple

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

		# do the threading
		if self._check_interval_enable == False:
			return
		elif self._async_checking == True:
			if self._verbose:print("Skipping async check, already started")
			return # already running the bg thread
		elif self._update_ready == None:
			# return (self._update_ready,self._update_version,self._update_link)
			self.start_async_check_update(False, callback)

	def check_for_update_now(self, callback=None):
		if self._verbose: print("Check update pressed, first getting current status")
		if self._async_checking == True:
			if self._verbose:print("Skipping async check, already started")
			return # already running the bg thread
		elif self._update_ready == None:
			# return (self._update_ready,self._update_version,self._update_link)
			self.start_async_check_update(True, callback)
		else:
			self._update_ready = None
			self.start_async_check_update(True, callback)


	# this function is not async, will always return in sequential fashion
	# but should have a parent which calls it in another thread
	def check_for_update(self, now=False):
		if self._verbose:print("Checking for update function")

		# avoid running again in if already run once in BG, just return past result
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
			if self.verbose:print("Aborting check for updated, check interval not reached")
			return (False, None, None)
		
		# check if using tags or releases
		# note that if called the first time, this will pull tags from online
		if self._fake_install == True:
			if self._verbose:print("fake_install = True, setting fake version as ready")
			self._update_ready = True
			self._update_version = "(999,999,999)"
			self._update_link = "http://127.0.0.1"
			
			return (self._update_ready, self._update_version, self._update_link)
		self.get_tags() # sets self._tags and self._tag_latest
		self._json["last_check"] = str(datetime.now())
		self.save_updater_json()

		if len(self._tags) == 0:
			if self._verbose:print("No tag found on this repository")
			self._update_ready = False
			self._connection_failed = True
			return (False, None, None)
		new_version = self.version_tuple_from_text(self.tag_latest)


		link = self._tags[0]["zipball_url"] # best way?
		if new_version != self._current_version:
			self._update_ready = True
			self._update_version = new_version
			self._update_link = link
			self.save_updater_json()
			return (True, new_version, link)

		# need to make clean version of git tag/release name.
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
			raise ValueError("Verion tag not found: "+revert_tag)
		new_version = self.version_tuple_from_text(self.tag_latest)
		self._update_version = new_version
		self._update_link = tg["zipball_url"]


	# consider if update available and it's been long enough since last check

	def run_update(self, force=False, revert_tag=None, clean=False, callback=None):
		
		# revert_tag: could e.g. get from dropdown list
		# different versions of the addon to revert back to
		# clean: ie fully remove folder and re-add addon
		# (not literally since the code is running from here & we want a revertable copy)
		self._json["update_ready"] = False
		self._json["version_text"] = {}

		if revert_tag != None:
			self.set_tag(revert_tag)
			self._update_ready = True


		if self.verbose:print("Running update")

		if self._fake_install == True:
			# change to True, to trigger the reload/"update isntalled" handler
			if self._verbose:print("fake_install = True, just reloading and running any trigger")
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
				return # stopped, no link available - run check update first or set tag
			if self.verbose:print("Forcing update")
			# first do a check
			if self._update_link == None:
				if self.verbose:print("Update stopped, could not get link")
				return
			self.stage_repository(self._update_link)
			self.upack_staged_zip()
			# would need to compare against other versions held in tags

		# run the user's callback if provided
		if callback != None:callback()

		# return something meaningful, 0 means it worked
		return 0


	def past_interval_timestamp(self):
		if self._check_interval_enable == False:
			return True # ie this exact feature is disabled, allow as if interval passed
		
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
				if self._verbose:print("Determined it's time to check for udpates")
				return True
			else:
				if self._verbose:print("Determined it's not yet time to check for udpates")
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
			print("Wrote out json settings to file, with the contents:")
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
		updater.update_ready = None # reset so you could check update again

	def ignore_update(self):
		self._json["ignore"] = True
		self.save_updater_json()

	# -------------------------------------------------------------------------
	# ASYNC stuff...
	# EDIT: needs to be threaded unfortunately.
	# Come back to later.
	# -------------------------------------------------------------------------

	def start_async_check_update(self, now=False,callback=None):
		if self._async_checking == True:
			return
		if self._verbose: print("Starting background checking thread")
		check_thread = threading.Thread(target=self.async_check_update, args=(now,callback,))
		check_thread.daemon = True
		check_thread.start()
		
		return True

	def async_check_update(self, now, callback=None):
		self._async_checking = True
		if self._verbose:print("BG: Checking for update now in background")
		# time.sleep(3) # to test background, in case internet too fast to tell
		self.check_for_update(now=now)
		if self._verbose:print("BG: Finished checking for update, doing callback")
		if callback != None:callback(self._update_ready)
		self._async_checking = False

	def end_async_check_update():
		# could return popup if condition met
		
		return True


# -----------------------------------------------------------------------------
# The module-shared class instance,
# should be what's imported to other files
# -----------------------------------------------------------------------------

Updater = Singleton_updater()

