FROM ubuntu:24.04

# Non-interactive and locale
ENV DEBIAN_FRONTEND=noninteractive

# System dependencies (R 4.4+ from CRAN, wget, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        wget \
        ca-certificates \
        gnupg \
        software-properties-common \
        dirmngr \
        locales \
        git && \
    locale-gen en_GB.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

ENV LANG=en_GB.UTF-8
ENV LC_ALL=en_GB.UTF-8

# Add CRAN repo for R >= 4.4 on Ubuntu 24.04 (noble)
RUN wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc | \
        gpg --dearmor -o /usr/share/keyrings/r-project.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/r-project.gpg] https://cloud.r-project.org/bin/linux/ubuntu noble-cran40/" \
        > /etc/apt/sources.list.d/r-project.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        r-base \
        r-base-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Quarto CLI
RUN wget -qO /tmp/quarto.deb https://quarto.org/download/latest/quarto-linux-amd64.deb && \
    apt-get update && \
    apt-get install -y /tmp/quarto.deb && \
    rm /tmp/quarto.deb && \
    rm -rf /var/lib/apt/lists/*

# Install Miniconda
ENV CONDA_DIR=/opt/conda
RUN wget -qO /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && \
    bash /tmp/miniconda.sh -b -p "$CONDA_DIR" && \
    rm /tmp/miniconda.sh
ENV PATH="$CONDA_DIR/bin:${PATH}"

# Configure conda for non-interactive use and faster solving
RUN conda config --system --set always_yes yes && \
    conda config --system --set changeps1 no

# Accept Anaconda ToS for required channels in non-interactive builds
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Copy project
WORKDIR /workspace
COPY . /workspace

# Remove .Renviron if it was copied (to avoid hardcoded host paths)
RUN rm -f /workspace/.Renviron

# Create the conda environment
RUN conda env create -f dev_environment/environment.yml

# Install the local package using the env's pip (no conda activate needed)
RUN /opt/conda/envs/vidigi_package_dev/bin/pip install -e /workspace

# Make the environment active by default
ENV CONDA_DEFAULT_ENV=vidigi_package_dev
ENV PATH="/opt/conda/envs/vidigi_package_dev/bin:${PATH}"
RUN echo "conda activate vidigi_package_dev" >> /root/.bashrc

# R: set renv path and restore packages
ENV RENV_PATHS_LIBRARY=/workspace/renv/library

# Install renv and restore R packages
RUN Rscript -e "install.packages('renv', repos = 'https://cloud.r-project.org')" && \
    Rscript -e "renv::restore()"

# Set conda environment as default for reticulate
ENV RETICULATE_PYTHON=/opt/conda/envs/vidigi_package_dev/bin/python

# Default command
CMD ["/bin/bash"]