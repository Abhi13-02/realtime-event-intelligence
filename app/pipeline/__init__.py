"""Article pipeline package.

DELIBERATELY EMPTY — do not re-export submodules here.

This used to eagerly import orchestrator, models, interfaces and exceptions,
which meant that importing ANY pipeline submodule pulled in stages.py and its
`import numpy`. Once the images were split by weight that became a boot
failure: app/adapters/ai/client.py implements EmbeddingInterface from
app.pipeline.interfaces, and the backend runs the slim image, which has no
numpy. The whole gateway would have crashed on startup.

Import the submodule you need directly:

    from app.pipeline.interfaces import EmbeddingInterface
    from app.pipeline.orchestrator import ArticlePipeline

Nothing outside this package used the re-exports, so removing them cost
nothing and keeps interfaces.py reachable from a torch-free, numpy-free image.
"""
