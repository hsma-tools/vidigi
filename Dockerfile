# Start from a base R image
FROM rocker/r-ver:4.4.1

# Install system dependencies for R and Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libharfbuzz-dev \
        libfribidi-dev \
        libfontconfig1-dev \
        wget \
        curl \
        git \
        libpng-dev \
        libxml2-dev \
        libssl-dev \
        libcurl4-openssl-dev \
        python3-pip \
        python3-venv \
        build-essential \
        pandoc \
        libglpk-dev \
        libx11-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Quarto CLI
RUN wget -qO- https://quarto.org/download/latest/quarto-linux-amd64.deb > /tmp/quarto.deb && \
    dpkg -i /tmp/quarto.deb && \
    rm /tmp/quarto.deb

# Install Miniconda (for Python/Conda envs)
ENV CONDA_DIR=/opt/conda
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p $CONDA_DIR && \
    rm /tmp/miniconda.sh
ENV PATH=$CONDA_DIR/bin:$PATH

# Copy environment files and source code
WORKDIR /workspace
COPY . /workspace

# Accept Anaconda ToS for required channels in non-interactive builds
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Create the conda environment
RUN conda env create -f dev_environment/environment.yml

# Install the local package using the env's pip (no conda activate needed)
RUN /opt/conda/envs/vidigi_package_dev/bin/pip install -e /workspace

# Make the environment active by default
RUN echo "conda activate vidigi_package_dev" >> ~/.bashrc
ENV PATH=/opt/conda/envs/vidigi_package_dev/bin:$PATH

# Set path to renv
ENV RENV_PATHS_LIBRARY=/workspace/renv/library

# Install renv and restore R packages with rebuild
# Why rebuild? Because rocker/r-ver:4.4.1 is based on Ubuntu LTS with an older
# glibc, so the .so cannot be loaded. This means renv pulled a prebuilt binary
# (from its cache or our lockfile metadata) that expects glibc 2.38, but the
# base image's libc is older.
RUN Rscript -e "install.packages('renv', repos='https://cloud.r-project.org')" \
    && Rscript -e "Sys.setenv(RENV_CONFIG_CACHE_ENABLED = FALSE);" \
    && Rscript -e "renv::restore(rebuild = TRUE)"

# Set conda environment as default for reticulate
ENV RETICULATE_PYTHON=/opt/conda/envs/vidigi_package_dev/bin/python