# Contributing

We welcome contributions to `vidigi`. You can either:

* [Create a GitHub issue](https://github.com/hsma-tools/vidigi/issues).
* [Fork the repository](https://github.com/hsma-tools/vidigi/fork) and create a pull request.

This document contains guidance for working on this repository. Please be respectful and considerate - see the`CODE_OF_CONDUCT.md`.

<br>

## Updating the list of contributors

Any contributors to the repository should be recognised via `all-contributors`. If your name or contributions are missing from the README, or if you contributed in ways not captured by the current role emojis, then please feel free to update these. There are two ways to do this:

### 1. Via GitHub issues

This is the simplest option. Just create an issue like this example:

```
@all-contributors please add @githubuser for ...
```

Then list appropriate contribution types from [allcontributors.org/docs/en/emoji-key](https://allcontributors.org/docs/en/emoji-key) (e.g., code, review, doc, content, bug, ideas, infra).

### 2. Via the command line

Alternatively, you can update it from the command line. This may be preferable, as the bot will send emails to anyone tagged, and requires making pull requests into main (which may trigger various GitHub actions).

You'll need to install the [All-Contributors CLI tool](https://allcontributors.org/cli/installation/):

```
npm i -D all-contributors-cli
```

You can then run the following and select/enter relevant information when prompted:

```
npx all-contributors
```

If you want to remove specific contributions or people, edit the `.all-contributorsrc` file then run the following to regenerate the table in `README.md`. (Don't edit `README.md`, as it is just generated based on `.all-contributorsrc`).

```
npx all-contributors generate
```

<br>

## Development environment

### Python

A development environment is provided in `dev_environment/`. You can choose between:

* A conda environment (`environment.yml`).
* A virtualenv (`requirements.txt`).

You will also want to install the local vidigi package by running `pip install -e .`.

The conda environment will also install a suitable version of Python - if using virtualenv, you will need to configure this yourself.

This environment differs from `vidigi`'s dependencies (`pyproject.toml`), as it contains the packages needed to e.g., generate documentation, run tests, lint code, and build the package.

If you make changes to the development environment, please ensure you change it in all locations:

* [ ] `dev_environment/environment.yml`
* [ ] `dev_environment/requirements.txt`

### R

R is **not** currently required to build vidigi's documentation. R was previously used to compare `vidigi` against similar packages in R (bupaR, processanimateR), but that comparison content (`examples/ARCHIVE_vidigi_vs_bupar/`, `examples/r_simmer/`, `vidigi_docs/prep_vidigi_outputs_for_bupar_processing.ipynb`) is excluded from the active Quarto render scope, and the CI docs-build workflow ([`documentation_deploy.yml`](.github/workflows/documentation_deploy.yml)) no longer uses Docker or installs R at all.

The old R/renv toolchain files (`renv.lock`, `DESCRIPTION`, `.Rprofile`, `.renvignore`, `vidigi.Rproj`, `renv/`) are kept for reference under [`archive/r_environment/`](archive/r_environment/) rather than deleted, in case this comparison content is revived in future.

#### Reviving R support

If you want to bring R support back:

1. Move the files out of `archive/r_environment/` back to the repo root (this restores `renv`'s and RStudio's expected relative paths, e.g. `.Rprofile`'s `source("renv/activate.R")`).
2. For a starting point on installing R again, see the archived [`archive/docker_quarto_workflow/Dockerfile`](archive/docker_quarto_workflow/Dockerfile) and [`archive/docker_quarto_workflow/docker_quarto.yml`](archive/docker_quarto_workflow/docker_quarto.yml), or the last commit with a working (rocker-based) R install, [`14a363b`](https://github.com/hsma-tools/vidigi/commit/14a363b).
3. Expect to re-validate the R/renv install from scratch: R was dropped after a long run of CI build failures (rocker base image issues, CRAN mirror problems, package version pinning - see commits `3269691` through `b9646b6` in the git history), so it wasn't reliable even when last in use.
4. Re-add `examples/ARCHIVE_vidigi_vs_bupar/` and/or `examples/r_simmer/` to `_quarto.yml`'s `project.render` list (remove their `!` exclusion entries) once R renders successfully again.

<br>

## Documentation

The vidigi documentation is created using quarto and `quartodoc`. You can generate it locally by running:

```
quartodoc build
quarto render
```

It is rendered via GitHub Actions ([`documentation_deploy.yml`](.github/workflows/documentation_deploy.yml)) and hosted on GitHub Pages. The workflow installs Quarto and vidigi's dependencies directly on the Actions runner and renders/publishes from there - no Docker container is involved.

A Docker-based build was previously used (to reuse a cached environment across runs, back when R was part of the docs build), but with R no longer required it added more overhead than it saved. It's kept for reference under [`archive/docker_quarto_workflow/`](archive/docker_quarto_workflow/) in case a containerized build is needed again.

<br>

## Linting

We use Black to auto-format the vidigi package, setting the maximum line length to 79 to comply with PEP 8 - simply run:

```
black vidigi --line-length=79
```

We also run other linters to manually check and edit package style:

```
# Checks PEP8-style, basic errors and code complexity
flake8 vidigi

# Run flake8 on .ipynb files
nbqa flake8 examples

# Run flake8 on .qmd files
lintquarto -l flake8 -p vidigi_docs
```
