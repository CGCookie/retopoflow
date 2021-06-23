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
VERSION         = v3.2.1-alpha
# VERSION         = v3.2.1-beta
# VERSION         = v3.2.1
GIT_TAG         = "v3.2.1"
GIT_TAG_MESSAGE = "This is the alpha release for RetopoFlow 3.2.1."
# GIT_TAG_MESSAGE = "This is the beta release for RetopoFlow 3.2.1."
# GIT_TAG_MESSAGE = "This is the official release for RetopoFlow 3.2.1."

BUILD_DIR         = ../retopoflow_release
INSTALL_DIR       = ~/.config/blender/addons
DEBUG_CLEANUP     = $(shell pwd)/addon_common/scripts/strip_debugging.py
DOCS_REBUILD      = $(shell pwd)/scripts/prep_help_for_online.py
CREATE_THUMBNAILS = $(shell pwd)/scripts/create_thumbnails.py
CGCOOKIE_BUILT    = $(NAME)/.cgcookie
ZIP_FILE          = $(NAME)_$(VERSION).zip
TGZ_FILE          = $(NAME)_$(VERSION).tar.gz


.DEFAULT_GOAL 	:= build

.PHONY: docs


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


docs:
	# rebuild online docs
	python3 $(DOCS_REBUILD)

docs-serve:
	cd docs && bundle exec jekyll serve

docs-clean:
	cd docs && bundle exec jekyll clean

check:
	# check that we don't have case-conflicting filenames (ex: utils.py Utils.py)
	# most Windows setups have issues with these
	./scripts/detect_filename_case_conflicts.py

thumbnails:
	# create thumbnails
	cd help && python3 $(CREATE_THUMBNAILS)

build: check
	mkdir -p $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/$(NAME)

	# copy files over to build folder
	# note: rsync flag -a == archive (same as -rlptgoD)
	rsync -av --progress . $(BUILD_DIR)/$(NAME) --exclude-from="Makefile_excludes"
	# touch file so that we know it was packaged by us
	cd $(BUILD_DIR) && echo "This file indicates that CG Cookie built this version of RetopoFlow." > $(CGCOOKIE_BUILT)
	# run debug cleanup
	cd $(BUILD_DIR) && python3 $(DEBUG_CLEANUP) "YES!"
	# create thumbnails
	cd $(BUILD_DIR)/$(NAME)/help && python3 $(CREATE_THUMBNAILS)
	# zip it!
	cd $(BUILD_DIR) && zip -r $(ZIP_FILE) $(NAME)

	@echo
	@echo $(NAME)" "$(VERSION)" is ready"

install:
	rm -r $(INSTALL_DIR)/$(NAME)
	cp -r $(BUILD_DIR)/$(NAME) $(INSTALL_DIR)/$(NAME)

