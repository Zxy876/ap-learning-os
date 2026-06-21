# Runtime Data Directory

This directory is intentionally not used for source code.

The Learning OS writes local runtime JSON here, including generated task state, PDF text indexes, and section indexes. These files are ignored by git because they are machine-specific and may contain local paths or private study state.

Source code lives in the repository root:

- `learning_os.py`
- `blackboard_server.py`
- `config.json`
- `launchers/`

