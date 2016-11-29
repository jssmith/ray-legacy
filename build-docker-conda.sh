#!/bin/bash

tar --exclude './docker' -c . > ./docker/deploy-conda/ray.tar
docker build --no-cache -t ray-project/ray:deploy-conda docker/deploy-conda
rm ./docker/deploy-conda/ray.tar
