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

To build the documentation, you will also need to set-up an appropriate R environment, as we compare `vidigi` to some similar packages in R.

You can find the version of R used listed in the `renv.lock` file - we'd suggest using `rig` to install this.

To fetch the required R packages, you can first try using `renv::restore()`. This will attempt to create the exact environment description in the `renv.lock` file. However, if you encounter problems, you can try using the `DESCRIPTION` file instead.

The `DESCRIPTION` file lists all the required R packages (though with no pinned dependencies). You'll want to open R, initialise renv, install (based on `DESCRIPTION`), and then record this using `renv::snapshot()` - for example, from the terminal:

```
R
renv::init()
renv::install()
renv::snapshot()
```

To quit R from the terminal (e.g., if need to restart it after initialising renv), use the command `q()`.

To install the package `processanimateR` via `renv::install()`, you'll need to add GitHub authentication credentials (as it pulls the package from GitHub, since it was removed from CRAN). If you don't, it will default to looking on CRAN and fail with the error `package 'processanimateR' is not available`. Alternatively, you can get it manually using the package `remotes`:

```
install.packages("remotes")
remotes::install_github("bupaverse/processanimateR")
```

**Warning:** This package can take a long time to install.

**Note:** We use renv snapshot type `all` as `implicit` mode excludes packages it can't detect as dependencies, but we have `reticulate` which is necessary but doesn't appear like a typical dependency (e.g., `library(reticulate)`).

<br>

## Documentation

The vidigi documentation is created using quarto and `quartodoc`. You can generate it locally by running:

```
quartodoc build
quarto render
```

It is rendered via GitHub actions and hosted on GitHub pages. The action creates a Docker image hosted on GitHub Container Registry. This makes it more efficient, as it doesn't need to rebuild the environment when no changes have been made to the packages installed.

To test rendering the quarto site in the docker container locally...

Build image:

```
sudo docker build -t vidigi .
```

Render quarto project inside container:

```
docker run --rm vidigi quarto render
```

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
