#!/bin/bash
# Build iris-timelineexport-module and install it into the IRIS containers.
# Compatible with both Podman and Docker.

set -e

CONTAINER_RT=$(command -v podman || command -v docker)
if [ -z "$CONTAINER_RT" ]; then
    echo "ERROR: Neither podman nor docker found"
    exit 1
fi

Help() {
    echo "Build IRIS Timeline Export module and install it into the IRIS containers."
    echo
    echo "Syntax: $0 [-a|h][-w NAME][-p NAME]"
    echo "options:"
    echo " -a         Also install to the app container (required on first install or config changes)"
    echo " -w NAME    Worker container name (default: iriswebapp_worker)"
    echo " -p NAME    App container name (default: iriswebapp_app)"
    echo " -h         Print this help"
}

CheckPrerequisite() {
    PYTHON=$(command -v python3 || command -v python)
    if [ -z "$PYTHON" ]; then
        echo "ERROR: Python could not be found"
        exit 1
    fi
    if ! $PYTHON -m pip --version > /dev/null 2>&1; then
        echo "ERROR: pip could not be found"
        exit 1
    fi
}

Run() {
    CheckPrerequisite

    echo "[BUILDnPUSH2IRIS] Building wheel..."
    $PYTHON -m pip wheel . --no-deps -w dist/

    latest=$(ls -Art1 ./dist/*.whl | tail -n 1)
    module=$(basename "$latest")
    echo "[BUILDnPUSH2IRIS] Built: $latest"

    echo "[BUILDnPUSH2IRIS] Installing into worker container ($worker_container_name)..."
    $CONTAINER_RT cp "$latest" "$worker_container_name:/iriswebapp/dependencies/$module"
    $CONTAINER_RT exec "$worker_container_name" pip3 install "dependencies/$module" --no-deps --force-reinstall --quiet
    $CONTAINER_RT restart "$worker_container_name"

    if [ "$a_Flag" = true ]; then
        echo "[BUILDnPUSH2IRIS] Installing into app container ($app_container_name)..."
        $CONTAINER_RT cp "$latest" "$app_container_name:/iriswebapp/dependencies/$module"
        $CONTAINER_RT exec "$app_container_name" pip3 install "dependencies/$module" --no-deps --force-reinstall --quiet
        $CONTAINER_RT restart "$app_container_name"
    fi

    echo "[BUILDnPUSH2IRIS] Restarting nginx..."
    $CONTAINER_RT restart "$nginx_container_name"

    echo "[BUILDnPUSH2IRIS] Done!"
}

a_Flag=false
worker_container_name="iriswebapp_worker"
app_container_name="iriswebapp_app"
nginx_container_name="iriswebapp_nginx"

while getopts ":haw:p:" option; do
    case $option in
        h) Help; exit;;
        a) a_Flag=true;;
        w) worker_container_name=$OPTARG;;
        p) app_container_name=$OPTARG;;
        \?) echo "ERROR: Invalid option"; exit 1;;
        :)  echo "ERROR: Option -$OPTARG requires an argument"; exit 1;;
    esac
done

if [ "$a_Flag" = true ]; then
    echo "[BUILDnPUSH2IRIS] Deploying to Worker + App containers"
else
    echo "[BUILDnPUSH2IRIS] Deploying to Worker container only"
fi

Run
