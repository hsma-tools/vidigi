# Contributing

We welcome contributions to `vidigi`. You can either:

* [Create a GitHub issue](https://github.com/hsma-tools/vidigi/issuess).
* [Fork the repository](https://github.com/hsma-tools/vidigi/fork) and create a pull request.

This document contains guidance for working on this repository. Please be respectful and considerate - see the`CODE_OF_CONDUCT.md`.

## Development environment

### Python

A development environment is provided in `dev_environment/`. You can choose between:

* A conda environment (`environment.yml`).
* A virtualenv (`requirements.txt`).

These will install your local vidigi package (`-e .`) and the required package for development. The conda environment will also install a suitable version of Python - if using virtualenv, you will need to configure this yourself.

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

## Documentation

The vidigi documentation is created using quarto. You can generate it locally by running:

```
quarto render vidigi_docs
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