"""What the transcript means: claims, entities, topics, search, synthesis.

A library the layers above call. It reads what `sift_core` produced (via
`app/store`) and never calls back into ingest, the API, or the pipeline.
"""
