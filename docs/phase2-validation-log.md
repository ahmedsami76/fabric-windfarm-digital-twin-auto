# Phase 2 validation log

The record of the first deployment of Phase 2, which began on 20 November 2026 at about 23:00 Houston time: what went wrong, why, and what was changed. The workstation is Ubuntu on WSL; the workspace and capacity are those of Phase 1.

## Progress

The user reported the guide as done at 23:41, 40 minutes after starting. "Reported" means said without output.

| Step | Result | Notes |
|---|---|---|
| 1. Prepared views in the Eventhouse | Reported done | |
| 2. Import the notebooks | Done | |
| 3. Build the model tables (notebook 05) | Passed | Notebook 06 found all twelve tables. The check output, with the hand-over from history to live, was not sent. |
| 4. Build the semantic model (notebook 06) | Passed at the second attempt | Obstacle 1 |
| 5. Test the model (notebook 07) | Reported done after the third attempt | Obstacles 2 and 3. Whether all eleven checks printed PASS was not sent. |
| 6. Build the report (notebook 08) | Reported done | Whether every visual renders was not confirmed. |
| 7. Keep it current | Not reported | |

## Obstacles and what was changed

| # | Step | What happened | Cause | Changed | Checked |
|---|---|---|---|---|---|
| 1 | 4 | Notebook 06, cell 4: `TypeError: got an unexpected keyword argument 'overwrite'` from `generate_direct_lake_semantic_model`. Nothing was created. | The call was written from the library's online documentation ("latest"), which describes code that is not released. Release 0.15.2, which the notebook installs, has no `overwrite` argument and stops when a model of the name exists. | The notebook creates the model only when it does not exist, with the table names given as a dictionary (model name to Lakehouse table), which the release supports; the renaming step is gone. On a second run it keeps the model and replaces relationships and measures. Every other library call of notebooks 06 to 08 was compared with the source of release 0.15.2: no further difference. | Against the source code of the release, downloaded from the package index. The two corrected cells then ran in Fabric, pasted by hand; the notebook as a whole has not run again. |
| 2 | 5 | Notebook 07, cell 3: `ModuleNotFoundError: No module named 'sempy_labs'`. | Notebook 07 uses the library to refresh the model and had no cell that installs it. Notebooks 06 and 08 have one; each notebook runs in its own session. | Notebook 07 starts with the same `%pip install` cell. A test now fails when a notebook imports the library without installing it first. | Test. The notebook as delivered, with the cell in first place, has not run in Fabric. |
| 3 | 5 | Notebook 07, last cell: `NameError: name 'acceptance_checks' is not defined`, after the install cell had been added by hand. | The cell had been placed below the collapsed cell that defines the checks. `%pip install` restarts the Python interpreter of a Fabric notebook; everything defined before it is lost. | In the repository's notebooks the install cell is the first code cell, and a test checks the order. The guide's failure table has the symptom. | Test |

## Lessons

- Documentation labelled "latest" is not the documentation of the latest release. Pin a version, download that version, and read the signatures in its code. This is lesson 10 of Phase 1 again, one day later, for a Python library instead of a CLI option.
- A notebook is tested as a whole only when it runs from the first cell in a fresh session. Hand edits in a live session hide order problems, and a collapsed cell is invisible to the person adding one.
- Ask for the output, not for "done". Three steps of this run are recorded as reported because nothing was sent.

## Still open

- The PASS and FAIL lines of notebook 07 and a look at the three report pages. Until they are seen, the 39 measures and the report definition count as run, not as verified.
- `04-prepared-views.kql` in the Eventhouse: the result of its check query.
- Which Spark runtime the workspace uses.
- `Scada10Min()` and notebook 05 implement the same rules twice; nothing compares them.
