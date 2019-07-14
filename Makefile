# ---------------------------------------------------------------
# Makefile for RetopoFlow
# Jonathan Williamson - <jonathan@cgcookie.com>

# Originally created by Diego Gangl - <diego@sinestesia.co>
# ---------------------------------------------------------------



# /./././././././././././././././././././././././././././././././
# SETTINGS
# /./././././././././././././././././././././././././././././././

NAME            = RetopoFlow
VERSION         = v2.80.0
GIT_TAG         = v2.80.0
GIT_TAG_MESSAGE = "Version 2.80.0"

BUILD_DIR       = ../retopoflow_release
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

	# rsync flag -a == archive (same as -rlptgoD)
	rsync -av --progress . $(BUILD_DIR)/$(NAME) --exclude-from="Makefile_excludes"
	cd $(BUILD_DIR) ; zip -r $(ZIP_FILE) $(NAME)

	@echo
	@echo $(NAME)" "$(VERSION)" is ready"
