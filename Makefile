 
# ---------------------------------------------------------------
# Makefile for RetopoFlow
# Jonathan Williamson - <jonathan@cgcookie.com>

# Originally created by Diego Gangl - <diego@sinestesia.co>
# ---------------------------------------------------------------
 
 
# /./././././././././././././././././././././././././././././././
# SETTINGS
# /./././././././././././././././././././././././././././././././
 
NAME            = RetopoFlow
VERSION         = 1.2.0_beta
BUILD_DIR       = ../release
BUILD_FILE      = $(BUILD_DIR)/$(NAME)_$(VERSION).zip
FILES           = *.py help/* icons/* lib/*.py lib/classes/* op_contours/*.py op_edgeslide/*.py op_eyedropper/*.py op_loopcut/*.py op_polypen/*.py op_polystrips/*.py

.DEFAULT_GOAL 	:= build
 
 
# /./././././././././././././././././././././././././././././././
# TARGETS
# /./././././././././././././././././././././././././././././././
 

clean:
	rm -rf $(BUILD_FILE)
	@echo "Release zip deleted - " $(BUILD_FILE)
 
 
build:
 
	mkdir -p $(BUILD_DIR)
 
	mkdir -p $(BUILD_DIR)/$(NAME)

	# cp -R $(FILES) $(BUILD_DIR)/$(NAME)
	rsync -av --progress . $(BUILD_DIR)/$(NAME) --exclude="__pycache__" --exclude=".*/" --exclude="Makefile" --exclude="*.md"
 
	@echo
	@echo $(NAME)" "$(VERSION) " is ready"
 