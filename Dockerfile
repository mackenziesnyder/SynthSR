# use python 3.8 slim
FROM python:3.8-slim

# install system dependencies
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    pkg-config \
    libhdf5-dev \
    libprotobuf-dev \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# define the working directory inside the container
WORKDIR /app

# copy the SynthSR repo and other necessary files to the container
COPY . /app

# upgrade pip and install the required Python packages
RUN pip install --upgrade pip
RUN pip install --no-cache-dir \
    tensorflow==2.12.0 \
    keras==2.12.0 \
    protobuf==3.20.3 \
    numpy==1.23.5 \
    nibabel==5.0.1 \
    matplotlib==3.6.2
