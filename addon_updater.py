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
myUpdater.set_check_frequency(months=0,weeks=0,days=0,minutes=5) # optional
(update_ready, version, link) = myUpdater.check_for_update(force=false)
myUpdater.update_appropriately() # only update if time & new version
myUpdater.update_now() # force update regardless



"""

import urllib.request
import urllib
import os
import json
import zipfile
import shutil

# blender imports, used in limited cases
import bpy
import addon_utils

# -----------------------------------------------------------------------------
# Define error messages/notices & hard coded globals
# -----------------------------------------------------------------------------

DEFAULT_API_URL = "https://api.github.com" # plausibly could be some other system
DEFAULT_TIMEOUT = 10
DEFAULT_PER_PAGE = 30

ERRORS ={
	1:"Unknown error"
}


# -----------------------------------------------------------------------------
# The main class
# -----------------------------------------------------------------------------

class Singleton_updater(object):
	"""
	This is the singleton class to reference a copy from
	"""

	# constructor
	#def __init__(self, user, repo, api_url=DEFAULT_API_URL, timeout=DEFAULT_TIMEOUT, 
	#			use_releases=True, current_version = None, stage_path="//"):
	
	def __init__(self):
		"""
		:param user: string # name of the user owning the repository
		:param repo: string # name of the repository
		:param api_url: string # should just be the github api link
		:param timeout: integer # request timeout
		:param use_releases: bool # else uses tags for release version checking
		:param current_version: tuple # typically 3 values meaning the version #
		"""

		self._user = None
		self._repo = None
		self._api_url = DEFAULT_API_URL
		self._current_version = None
		self._tags = []
		self._tag_latest = None
		self._tag_names = []
		self._releases = []
		self._release_latest = None
		 # "" # assume specific cachename, use addon?.cache
		#self._check_frequency = 0 # how often to auto-check for update, 0=never
		self._check_frequency_enable = False
		self._check_frequency_month = 0
		self._check_frequency_weeks = 2
		self._check_frequency_days = 0
		self._check_frequency_hours = 0
		self._check_frequency_minutes = 0

		self._verbose = False
		self._update_ready = None
		self._update_link = None
		self._update_version = None
		self._source_zip = None

		# get from module data
		self._addon = __name__
		if "." in self._addon:
			self._addon = self._addon[0:self._addon.index(".")]
		self._stage_path = os.path.join(os.path.dirname(__file__),
							self._addon+"_update_staging")
		




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
	def user(self):
		return self._user
	@user.setter
	def user(self, value):
		self._user = value

	@property
	def repo(self):
		return self._repo
	@repo.setter
	def repo(self, value):
		self._repo = value

	@property
	def api_url(self):
		return self._pai_url
	@api_url.setter
	def api_url(self, value):
		if self.check_is_url(value) == False:
			raise ValueError("Not a valid URL: " + value)
		self._api_url = value

	@property
	def stage_path(self):
		return self._stage_path
	@stage_path.setter
	def stage_path(self, value):
		print("NEW STAGE_PATH:",value)
		if value == None:
			print("Aborting assigning stage_path, it's null")
			return
		elif value != None and not os.path.exists(value):
			os.makedirs(value)
			# definitely check for errors here, user issues
		self._stage_path = value


	@property
	def tags(self):
		if self._tags == []:
			self._tags = self.get_tags() # full json
		tag_names = self.get_tag_names() # just name title

		return tag_names

	@property
	def tag_latest(self):
		if self._tag_latest == None:
			if self.verbose:print("Grabbing tags from server")
			self._tags = self.get_tags()
			self._tag_latest = self._tags[0]
			if self.verbose:print("Most recent tag found:",self._tags[0])
		return self._tag_latest["name"]

	@property
	def releases(self):
		if self._releases == []:
			self._releases = self.get_releases()
		return self._releases

	@property
	def release_latest(self):
		if self._releases_latest == None:
			# ie we haven't parsed the server yet, do it now
			self._releases = self.get_releases()
			self._release_latest = self._releases[0]
		return self._release_latest

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

	def set_check_frequency(enable=False, months=0, weeks=2, days=0, hours=0, minutes=0):
		# enabled = False, default initially will not check against frequency
		# if enabled, default is then 2 weeks

		if type(enable) is not bool:
			raise ValueError("Enable must be a boolean value")
		if type(months) is not int:
			raise ValueError("Months must be an integer value")
		if type(weeks) is not int:
			raise ValueError("Weeks must be an integer value")
		if type(days) is not int:
			raise ValueError("Days must be an integer value")
		if type(hours) is not int:
			raise ValueError("Hours must be an integer value")
		if type(minutes) is not int:
			raise ValueError("Minutes must be an integer value")


		# ensure they are integers
		if enable==False:
			self._check_frequency_enable = False
			if self._verbose:print("Auto-checking has been disabled")
		else:
			self._check_frequency_enable = True
			if self._verbose:print("Auto-checking has been enabled")
		
		self._check_frequency_enable,
		self._check_frequency_month,
		self._check_frequency_weeks,
		self._check_frequency_days,
		self._check_frequency_hours,
		self._check_frequency_minutes

		if self._verbose:print("updating frequency of checking")

	@property
	def check_frequency(self):
		return (self._check_frequency_enable,
				self._check_frequency_month,
				self._check_frequency_weeks,
				self._check_frequency_days,
				self._check_frequency_hours,
				self._check_frequency_minutes)

	@user.setter
	def check_frequency(self, value):
		raise ValueError("Check frequency is read-only")

	# -------------------------------------------------------------------------
	# Paramater validation related functions
	# -------------------------------------------------------------------------


	def check_is_url(self,url):
		if "http://" not in url:
			return False
		if "." not in url:
			return False
		return True

	def get_tag_names(self):
		tag_names = []
		for tag in self._tags:
			tag_names.append(tag["name"])
		return tag_names

	# other class stuff

	def __repr__(self):
		return "<Module updater from {a}>".format(a=__file__)

	def __str__(self):
		return "Updater, with user:{a}, repository:{b}, url:{c}".format(a=self._user,
									b=self._repo, c=self.form_repo_url())


	# -------------------------------------------------------------------------
	# API-related functions
	# -------------------------------------------------------------------------

	def form_repo_url(self):
		return DEFAULT_API_URL+"/repos/"+self.user+"/"+self.repo


	def get_tags(self):
		request = "/repos/"+self.user+"/"+self.repo+"/tags"
		# print("Request url: ",request)
		return self.get_api(request) # check error responses?


	# all API calls to base url
	def get_api_raw(self, url):
		request = urllib.request.Request(DEFAULT_API_URL + url)
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
		# ensure our folder is always "clean"
		local = self._stage_path

		#local = os.path.join(local, "update_staging")
		error = False

		# no, really should just remove eveyrthing but the cache if found
		# or use same as folder name but plus extension.. that could work
		print("localdir:",local)
		if os.path.isdir(local) == True:
			# try/except for permission errors or other OS errors!
			try:
				shutil.rmtree(local) 
				print("remove?")
				os.makedirs(local)
				print("re-added?")
			except:
				print("Error, couldn't remove existing staging directory")
				error = True
		else:
			try:
				print("os local dir:",local)
				os.makedirs(local)
			except:
				print("Error, couldn't make staging directory")
				error = True
		
		if error == True:
			print("Aborting update") # return error instead, with text standard
			return -1

		if self.verbose:print("Todo: create backup zip of current addon now")

		if self.verbose:print("Now retreiving the source zip")
		# really should have better error handling here..
		# also, jsut use FancyURLopener.. it's the same module, literally
		# try:
		self._source_zip = os.path.join(local,"source.zip")
		urllib.request.urlretrieve(url, self._source_zip)
		# except:


		return 0

	def upack_staged_zip(self):

		if os.path.isfile(self._source_zip) == False:
			print("Error, file not found")
			return -1

		if zipfile.is_zipfile(self._source_zip):
			with zipfile.ZipFile(self._source_zip) as zf:
				zf.extractall(os.path.join(self._stage_path,"source"))
		else:
			print("Not a zip file, future add support for just .py files")
			raise ValueError("Resulting file is not a zip")
		if self.verbose:print("Extracted source")

		# either directly in root of zip, or one folder level deep
		unpath = os.path.join(self._stage_path,"source")
		if os.path.isfile(os.path.join(unpath,"__init__.py")) == False:
			dirlist = os.listdir(unpath)
			if len(dirlist)>0:
				unpath = os.path.join(unpath,dirlist[0])

			if os.path.isfile(os.path.join(unpath,"__init__.py")) == False:
				print("not a valid addon found")
				raise ValueError("__init__ file not found in new source")

		# now commence merging in the two locations:
		# hard coded for now... should get from __file__?
		print("UNZSTAGE, unpath:",unpath,"  \n> origpath:",__file__)
		origpath = "/Users/patrickcrawford/Library/Application Support/Blender/2.76/scripts/addons/retopoflow/"
		self.deepMergeDirectory(origpath,unpath)
		self.reload_addon()


	# merge contents of folder 'merger' into folder 'base', without deleting existing
	def deepMergeDirectory(self,base,merger):
		if not os.path.exists(base):
			print("Base path does not exist")
			return -1
		elif not os.path.exists(merger):
			print("Merger path does not exist")
			return -1

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
		print("reloading addon...") # remove: __pycache__ ?
		addon_utils.modules(refresh=True)
		bpy.utils.refresh_script_paths()

		# not allowed in restricted context, such as register module
		#bpy.ops.script.reload()

		# toggle to refresh
		bpy.ops.wm.addon_disable(module=self._addon)
		bpy.ops.wm.addon_enable(module=self._addon)



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


	def check_for_update(self, now=False):
		if self._current_version == None:
			raise ValueError("No current_version property set for comparison")
		if self._repo == None:
			raise ValueError("No repo defined")
		if self._user == None:
			raise ValueError("No repo username defined")
			# fail silently?

		if now == False and self.past_interval_timestamp()==False:
			if self.verbose:print("Aborting check for updated, check interval not reached")
			return (False, None, None)

		# check if using tags or releases
		# note that if called the first time, this will pull tags
		# override with force?
		new_version = self.version_tuple_from_text(self.tag_latest)
		link = self._tags[0]["zipball_url"] # best way?
		if new_version != self._current_version:
			self._update_ready = True
			self._update_version = new_version
			self._update_link = link
			return (True, new_version, link)

		# need to make clean version of git tag/release name.
		self._update_ready = False
		self._update_version = None
		self._update_link = None
		return (False, None, None)

	# consider if update available and it's been long enough since last check

	def run_update(self, force=False, revert_tag=None, clean=False):
		
		# revert_tag: could e.g. get from dropdown list
		# different versions of the addon to revert back to
		# clean: ie fully remove folder and re-add addon
		# (not literally since the code is running from here & we want a revertable copy)

		if self.verbose:print("Running updates")

		if force==False:
			# should we not check for this here?
			if self.past_interval_timestamp()==False:
				if self.verbose:print("Update stopped, not past interval date")
				return 1 # stopped
			elif self._update_ready != True:
				if self.verbose:print("Update stopped, new version not ready")
				return 1 # stopped
			elif self._update_link == None:
				# this shouldn't happen if update is ready
				if self.verbose:print("Update stopped, update link unavailable")
				return 1 # stopped

			if self.verbose:print("Staging update")
			result = self.stage_repository(self._update_link)
			if result == 0:
				# everythign worked fine
				self.upack_staged_zip()
			else:
				print("Error with stage_repository:",result)
				


		else:
			if self._update_link == None:
				return 2 # stopped, no link available - run check update first or set tag
			if self.verbose:print("Forcing update")
			self.stage_repository(self._update_link) # how does this work with force/getting link?
			# would need to compare against other versions held in tags

		# return something meaningful, 0 means it worked
		return 0


	def past_interval_timestamp(self):
		if self._check_frequency_enable == False:
			return True # ie this exact feature is disabled, allow as if interval passed
		if self._stage_path == None:
			return True # not setup, so just return true and allow update

		# then look for cache file... read.. etc
		# only if read in file says datestamp is in future of current time return false
		return True # for now, always be true





# -----------------------------------------------------------------------------
# The module-shared class instance,
# should be what's imported to other files
# -----------------------------------------------------------------------------

Updater = Singleton_updater()

