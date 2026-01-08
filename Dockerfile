FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ============================================================
# STAGE 1: Install ALL system dependencies FIRST
# ============================================================
# This must happen before Conda to ensure R compiles against
# system libraries, not conda libraries
RUN set -eux; \
    # retry apt-get update a few times in case mirrors are mid-sync
    for i in 1 2 3; do \
      apt-get update && break; \
      echo "apt-get update failed, retrying ($i/3)..."; \
      sleep 5; \
    done; \
    apt-get install -y --no-install-recommends \
        # Basic utilities
        wget ca-certificates gnupg software-properties-common \
        dirmngr locales git \
        # R compilation dependencies (CRITICAL for igraph)
        build-essential gfortran \
        libxml2-dev \
        libglpk-dev \
        libgmp-dev \
        libblas-dev \
        liblapack-dev \
        libcurl4-openssl-dev \
        libssl-dev && \
    locale-gen en_GB.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

# ============================================================
# STAGE 2: Install R from CRAN
# ============================================================
RUN wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc | \
    gpg --dearmor -o /usr/share/keyrings/r-project.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/r-project.gpg] https://cloud.r-project.org/bin/linux/ubuntu noble-cran40/" \
        > /etc/apt/sources.list.d/r-project.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends r-base r-base-dev && \
    rm -rf /var/lib/apt/lists/*

# ============================================================
# STAGE 3: Install Quarto
# ============================================================
RUN wget -qO /tmp/quarto.deb https://quarto.org/download/latest/quarto-linux-amd64.deb && \
    apt-get update && \
    apt-get install -y /tmp/quarto.deb && \
    rm /tmp/quarto.deb && \
    rm -rf /var/lib/apt/lists/*

# ============================================================
# STAGE 4: Install Miniconda (use explicit paths, not PATH)
# ============================================================
ENV CONDA_DIR=/opt/conda
RUN wget -qO /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && \
    bash /tmp/miniconda.sh -b -p "$CONDA_DIR" && \
    rm /tmp/miniconda.sh

RUN $CONDA_DIR/bin/conda config --system --set always_yes yes && \
    $CONDA_DIR/bin/conda config --system --set changeps1 no

# ============================================================
# STAGE 5: Set up project and create conda environment
# ============================================================
WORKDIR /workspace
COPY . /workspace
RUN rm -f /workspace/.Renviron

# Accept Anaconda ToS for required channels (non-interactive)
RUN $CONDA_DIR/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    $CONDA_DIR/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Create conda environment using explicit path (NOT in PATH yet)
RUN $CONDA_DIR/bin/conda env create -f dev_environment/environment.yml

# Install Python package
RUN /opt/conda/envs/vidigi_package_dev/bin/pip install -e /workspace

# ============================================================
# STAGE 6: Install R packages WITHOUT conda in PATH
# ============================================================
# CRITICAL: R package compilation must happen with system
# libraries, NOT conda libraries in PATH
ENV RENV_PATHS_LIBRARY=/workspace/renv/library

RUN Rscript -e "install.packages('renv', repos = 'https://cloud.r-project.org')" && \
    Rscript -e "renv::restore()"

# ============================================================
# STAGE 7: Activate conda environment for RUNTIME only
# ============================================================
# Now that R packages are installed, it's safe to add conda to PATH
ENV CONDA_DEFAULT_ENV=vidigi_package_dev
ENV PATH="/opt/conda/envs/vidigi_package_dev/bin:${PATH}"
ENV RETICULATE_PYTHON=/opt/conda/envs/vidigi_package_dev/bin/python

RUN echo "conda activate vidigi_package_dev" >> /root/.bashrc

CMD ["/bin/bash"]
