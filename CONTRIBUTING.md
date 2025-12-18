# Contributing

We welcome contributions to `vidigi`. You can either:

* [Create a GitHub issue](https://github.com/hsma-tools/vidigi/issuess).
* [Fork the repository](https://github.com/hsma-tools/vidigi/fork) and create a pull request.

This document contains guidance for working on this repository. Please be respectful and considerate - see the`CODE_OF_CONDUCT.md`.

## Development environment

A development environment is provided in `dev_environment/`. You can choose between:

* A conda environment (`environment.yml`).
* A virtualenv (`requirements.txt`).

These will install your local vidigi package (`-e .`) and the required package for development. The conda environment will also install a suitable version of Python - if using virtualenv, you will need to configure this yourself.

This environment differs from `vidigi`'s dependencies (`pyproject.toml`), as it contains the packages needed to e.g., generate documentation, run tests, lint code, and build the package.

If you make changes to the development environment, please ensure you change it in all locations:

* [ ] `dev_environment/environment.yml`
* [ ] `dev_environment/requirements.txt`

## Documentation

The vidigi documentation is created using quarto. You can generate it locally by running:

```
quarto render vidigi_docs
```