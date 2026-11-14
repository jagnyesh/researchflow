---
sprint: null
date: 2026-11-14
status: accepted
supersedes: []
superseded_by: null
related: [0037-codeql-alerts-cleared-in-code.md, 0036-formal-criteria-build-or-fail.md]
---

# Extraction writes every CSV or fails, and never lists a file it didn't write (#477)

**Problem.** `DataExtractionAgent._format_data` (`app/agents/extraction_agent.py`) writes one CSV per data element through `FileStorageService.save_csv`, then writes `all_data_combined.csv`. A data element is one kind of data the researcher asked to receive, such as diagnoses or lab results. A broad `except` wrapped the whole loop, so the first failed write ended it. Every later element and the combined file got no CSV. The fallback then listed every element as a file, and the elements before the failure appeared twice. The researcher got an incomplete package that said it was complete.

The name of a data element becomes its file name. Since ADR 0037, `save_csv` raises `ValueError` for a name with a path separator. Before that, a `/` failed the same way through an `OSError`. Free-text names aren't the only way in. The Formal Portal's own option `Procedures (CPT/HCPCS codes)` has a slash, and the Requirements Agent keeps the researcher's form choices as submitted. A local run of `_format_data` on the three form labels for diagnoses, procedures and lab results wrote only the diagnoses file. Its result listed four files. So every formal request that picked procedures lost its procedures file and every file after it.

**Decision (owner, 2026-11-14).**

- **One failed CSV fails the whole extraction.** `_format_data` re-raises instead of returning a partial package. The workflow already handles a raising extraction. It sets `extraction_complete` to false and records only the exception type and a reference in `state["error"]`. It now also empties `state["extracted_data_summary"]`. A reviewer who rejects at `qa_review` sends the request back through `data_extraction`. Before this change, a rerun that failed left the previous run's package in state, and QA passed it although the rerun's cleanup had deleted some of its files. QA then fails the empty package, and the request ends in the terminal `qa_failed` state with the escalation reason "QA validation failed". Nothing is delivered.
- **Names are checked before anything runs.** `_extract_data` and `_extract_preview` both check every requested name before the cohort query. A name that holds `/`, `\` or a NUL byte raises `ValueError`. The check runs before the extraction loops, so the name never reaches their log lines or `save_csv`'s failure log. The error and its log line give the element's position in the request, never its name. A name that can't be a file name is the shape of a path-traversal attempt, so the code never echoes it. Because the preview checks too, the request fails before anyone approves the full extraction. `FileStorageService`'s own guard (ADR 0037) stays as the backstop.
- **A write that fails for another reason removes what this run wrote.** A full disk or a permission error can still fail a write partway through. `_format_data` then deletes each file it started writing in this call and re-raises. That includes the half-written file of the write that failed. `create_download_zip` zips everything in the request's directory, so a leftover file could reach a later package. A failed delete is logged by exception type only and doesn't replace the original error.
- **The procedures option loses its slash.** `FORM_DATA_ELEMENTS` offers `Procedures (CPT, HCPCS codes)`. `canonical_data_element` drops the text in parentheses, so both spellings still dispatch to procedures.

**Considered options.**

- *Record the failed element and write the rest.* The package would at least hold the other files. But QA's completeness check reads records, not files. The failed element's records are still there, so QA would pass and delivery would ship a package without that file. A safe version needs changes to `qa_agent.py` and `delivery_agent.py`. It would also deliver a package that differs from what the researcher asked for.
- *Check each name inside `_format_data`, just before its write.* Every earlier element's query would still run. The extraction loop would log the unsafe name, and the earlier CSVs would already be on disk.
- *Name each CSV after its canonical element ID, such as `procedures.csv`.* Labels would never become file names. It would also rename every delivered file, and ADR 0037 rejected file names that differ from their element's name.
- *Leave files from a failed run on disk.* A rerun overwrites files with the same names. A file from an element the request no longer asks for would stay, and the next ZIP would include it.

**Consequences.**

- A request whose data elements include an unsafe name fails at the preview step, and again at full extraction if a reviewer approves past the preview. Before this change, it ran and delivered a partial package. A request stored with the old procedures label fails the same way when it reruns.
- The researcher doesn't see which element failed. The workflow shows `ValueError (ref: …)`, and the log line gives only the element's position.
- Two elements can still write to one file without any separator. A non-demographic element named `Demographics` overwrites the consolidated `Demographics.csv`. One named `all_data_combined` is overwritten by the combined file. `Lab A` and `lab a` collide on a case-insensitive filesystem. [#499](https://github.com/jagnyesh/researchflow/issues/499) tracks these collisions.
- The FHIR, REDCap and default branches of `_format_data` still list files they never write. Those formats aren't implemented, and delivery copies only `file_paths`, so this change leaves them alone.
