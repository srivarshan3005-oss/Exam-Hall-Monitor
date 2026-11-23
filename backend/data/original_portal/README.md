# Original-portal source data (NOT included in this release)

This folder used to hold a copy of the college's allocation data: the original `allotments.json`, the per-record
provenance file, the correction log and the rendered seating-chart evidence images. Those files contain real student
register numbers with their hall, seat and subject assignments, so they are **not distributed** with the public
release package.

To use the original-portal importer and its evidence tooling on a deployment that is authorised to hold this data,
place the files here (same layout) on that machine only:

    backend/data/original_portal/source/allotments.json
    backend/data/original_portal/allocation_provenance.json      (optional; built by scripts/build_original_provenance.py)
    backend/data/original_portal/provenance_corrections.json     (optional)
    backend/data/original_portal/seating_charts/*.png            (optional evidence images)

Do not commit these files to a repository or include them in a shared archive. The tests that need them skip
automatically when they are absent (see `backend/tests/test_original_import_real_data.py`).
