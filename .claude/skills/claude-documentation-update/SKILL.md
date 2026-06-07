---
name: claude-documentation-update
description: Read through the code files of the repository and adjust the documentation in the README.md file accordingly, check recent git commits for reference of what to update.
---

# Claude Documentation Update

When called:
  1. Find what's changed since README.md was last updated — run `git log -1 --format=%H -- README.md` to get that commit, then `git log <that-commit>..HEAD --name-only` (or `git diff <that-commit>..HEAD --stat`) to see which files moved since.
  2. Read the changed source files — scope to tracked project source only, e.g. `git ls-files '*.py'` excluding any vendored/virtualenv paths (`.venv*`), not every file matching `*.py` on disk.
  3. Before writing anything up, trace how each change actually behaves rather than inferring from the diff alone — e.g. does a new feature run in every code path the README describes, or only some (a fresh session vs. resuming from a crash backup, etc)? Read the surrounding code to confirm.
  4. Update README.md to reflect what you've confirmed. Keep "Additional Files / Directories" (or equivalent setup sections) limited to things the user must create before first run; things the program creates for itself at runtime belong in the usage description instead, not the setup checklist.
  5. Report what you changed and why directly in your reply to the user (in the terminal/chat) — never write a changelog, "recent updates" section, or any other persistent summary into README.md or any other file.

## Example
**Recent commits**: Added new feature x. (x.py added), 
**x.py**: Adds session saving functionality, 
**Old README.md**: 

RPG Game Sessions Project

Project by NAME

Run main.py to initiate a game session. 
Press ctrl + c to terminate the session permanently.

**New README.md**: 

RPG Game Sessions Project

Project by NAME

Run main.py to initiate the program.
When the program is run you will be asked wether to load a previous session or start a new session.
Press ctrl + c to terminate and save the session.

## Guidelines
- Remove outdated elements from the documentation only when those features no longer exist/apply.
- Keep additions to the documentation in the same style as the rest of the documentation.
- Do not adjust ROADMAP.md.
- Read only program code files, leave txt, md (except README), and data files alone.