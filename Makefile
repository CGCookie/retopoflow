# ---------------------------------------------------------------
# Makefile for RetopoFlow
# Jonathan Williamson - <jonathan@cgcookie.com>

# Originally created by Diego Gangl - <diego@sinestesia.co>
# ---------------------------------------------------------------



# /./././././././././././././././././././././././././././././././
# SETTINGS
# /./././././././././././././././././././././././././././././././

# TODO: get version from options
# TODO: warn if profiling is enabled!
# see https://ftp.gnu.org/old-gnu/Manuals/make-3.79.1/html_chapter/make_6.html

NAME            = RetopoFlow
VERSION         = v3.00.0
GIT_TAG         = "v3.00.0-rc.2"
GIT_TAG_MESSAGE = "This is the second release candidate for RetopoFlow 3.0.0. This version includes visual improvements, issue checkers, and a few bugs corrected."

BUILD_DIR       = ../retopoflow_release
DEBUG_CLEANUP   = $(NAME)/addon_common/scripts/strip_debugging.py
CGCOOKIE_BUILT  = $(NAME)/.cgcookie
ZIP_FILE        = $(NAME)_$(VERSION).zip
TGZ_FILE        = $(NAME)_$(VERSION).tar.gz


.DEFAULT_GOAL 	:= build


# /./././././././././././././././././././././././././././././././
# TARGETS
# /./././././././././././././././././././././././././././././././


clean:
	rm -rf $(BUILD_DIR)
	@echo "Release folder deleted"


gittag:
	# create a new annotated (-a) tag and push to GitHub
	git tag -a $(GIT_TAG) -m $(GIT_TAG_MESSAGE)
	git push origin $(GIT_TAG)


build:
	mkdir -p $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/$(NAME)

	# copy files over to build folder
	# note: rsync flag -a == archive (same as -rlptgoD)
	rsync -av --progress . $(BUILD_DIR)/$(NAME) --exclude-from="Makefile_excludes"
	# touch file so that we know it was packaged by us
	cd $(BUILD_DIR) && echo "This file indicates that CG Cookie built this version of RetopoFlow." > $(CGCOOKIE_BUILT)
	# run debug cleanup
	cd $(BUILD_DIR) && python3 $(DEBUG_CLEANUP) "YES!"
	# zip it!
	cd $(BUILD_DIR) && zip -r $(ZIP_FILE) $(NAME)

	@echo
	@echo $(NAME)" "$(VERSION)" is ready"
