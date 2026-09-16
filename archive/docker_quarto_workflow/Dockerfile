FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ============================================================
# STAGE 1: Install ALL system dependencies FIRST
# ============================================================
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
        dirmngr locales git curl \
        graphviz && \
    locale-gen en_GB.UTF-8 && \
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

# Only copy the environment file to prevent codebase changes from breaking cache
COPY dev_environment/environment.yml /workspace/dev_environment/environment.yml

# Accept Anaconda ToS for required channels (non-interactive)
RUN $CONDA_DIR/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    $CONDA_DIR/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Create conda environment using explicit path (NOT in PATH yet)
RUN $CONDA_DIR/bin/conda env create -f dev_environment/environment.yml

# ============================================================
# STAGE 6: Activate conda environment for RUNTIME only
# ============================================================
ENV CONDA_DEFAULT_ENV=vidigi_package_dev
ENV PATH="/opt/conda/envs/vidigi_package_dev/bin:${PATH}"

RUN echo "conda activate vidigi_package_dev" >> /root/.bashrc

CMD ["/bin/bash"]
