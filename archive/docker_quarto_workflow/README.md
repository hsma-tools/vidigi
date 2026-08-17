# Archived Docker-based docs deploy

This Docker/GHCR-image-based docs deploy workflow and its Dockerfile were replaced by
`.github/workflows/documentation_deploy.yml`, which builds docs directly on the GitHub
Actions runner (no container) now that R is no longer part of the docs build — see
`archive/r_environment/`. Kept for reference in case a containerized build is needed
again. See CONTRIBUTING.md for current docs-build instructions.
