# RetopoFlow: Project Structure

This document outlines the structure of the RetopoFlow codebase to help developers understand the organization and relationships between different components.

## Root Directory

```txt
/retopoflow/
├── addon_common/         # Common utilities shared with other CG Cookie addons
├── config/               # Configuration and options 
├── retopoflow/           # Core addon functionality
├── cy/                   # Cython acceleration modules
├── __init__.py           # Addon entry point
└── docs/                 # Documentation
```

## Core Modules

### Main Entry Points

- **retopoflow.py**: Main RetopoFlow class and operation
- **blenderregister.py**: Blender registration and UI integration
- **rftool.py**: Base class for all retopology tools

### Mesh Handling

- **rfmesh/**
  - **rfmesh.py**: Core mesh handling class with spatial operations
  - **rfmesh_wrapper.py**: Wrapper classes for BMesh elements

### Tools

RetopoFlow provides several specialized retopology tools, each in its own directory:

- **rftool_contours/**: Creates edge loops around a model
- **rftool_polypen/**: Pen tool for building mesh topology face by face
- **rftool_polystrips/**: Creates strips of polygons
- **rftool_strokes/**: Creates strips by drawing strokes
- **rftool_patches/**: Creates patch fills
- **rftool_loops/**: Creates edge loops
- **rftool_tweak/**: Adjusts vertex positions
- **rftool_relax/**: Evens out mesh geometry
- **rftool_knife/**: Cuts into existing geometry
- **rftool_select/**: Selection tool

Each tool directory typically contains:

- **[tool].py**: Main tool implementation
- **[tool]_ops.py**: Tool-specific operations
- **[tool]_utils.py**: Utility functions
- **[tool]_options.html**: UI options template

### UI and Systems

- **rfwidgets/**: Interactive widget system
- **rfwidget.py**: Base widget class for tool interactions
- **rfbrushes/**: Brush system for tools
- **html/**: HTML templates for UI components
- **helpsystem.py**: Documentation and help system
- **updatersystem.py**: Addon update mechanism
- **keymapsystem.py**: Keymap management

### Blender Integration

- **blenderregister.py**: Registration with Blender
- **rfoperators/**: Blender operators
- **rfoverlays/**: Viewport overlay system

## Support Modules

### Common Library (`addon_common/`)

The `addon_common/` directory contains shared utilities used across multiple CG Cookie addons:

- **common/**: Core utilities
  - **blender.py**: Blender-specific utilities
  - **debug.py**: Debugging tools
  - **decorators.py**: Function decorators
  - **fsm.py**: Finite State Machine implementation
  - **maths.py**: Mathematical utilities
  - **ui_core.py**: Core UI system
  - **ui_styling.py**: UI styling utilities
  - **utils.py**: General utilities

- **cookiecutter/**: Framework for Blender addons
  - **cookiecutter.py**: Base class for Blender addons

### Configuration (`config/`)

- **options.py**: Options and settings
- **keymaps.py**: Default keymap definitions

### Cython Modules (`cy/`)

- **target_accel.py**: Acceleration structure for target mesh
- **rfmesh_render.py**: Optimized mesh rendering

## Key Files

- **__init__.py**: Addon registration and metadata
- **retopoflow.py**: Main RetopoFlow class with initialization and lifecycle management
- **rftool.py**: Base class for all tools with common functionality
- **rfmesh/rfmesh.py**: Main mesh handling with spatial queries and operations

## Data Flow

1. **Initialization**: `__init__.py` → `blenderregister.py` → `retopoflow.py`
2. **Tool Selection**: `retopoflow.py` → `rf/rf_tools.py` → specific tool (e.g., `rftool_polypen/polypen.py`)
3. **Mesh Interaction**: Tool class → `rfmesh/rfmesh.py` → Blender BMesh operations
4. **UI Rendering**: Tool UI → `rf/rf_ui.py` → `addon_common/common/ui_core.py`

## Development Workflow

When developing RetopoFlow, focus on these key areas:

1. **Tool Implementation**: Extend existing tools or create new ones in the `rftool_*` directories
2. **Mesh Operations**: Enhance mesh handling in the `rfmesh` module
3. **UI Improvements**: Modify HTML templates and UI-related code
4. **Performance Optimization**: Update Cython modules for performance-critical operations

This structure facilitates modular development, allowing different components to be improved independently while maintaining the overall architecture.
