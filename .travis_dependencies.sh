#!/bin/sh

ENV_NAME="test-environment"
set -e

conda_create ()
{

    hash -r
    conda config --set always_yes yes --set changeps1 no
    conda update -q conda
    conda config --add channels pypi
    conda info -a
    deps='pip numpy scipy pandas requests nose coverage numpydoc matplotlib sphinx scikit-learn seaborn'

    conda create -q -n $ENV_NAME "python=$TRAVIS_PYTHON_VERSION" $deps
}

src="$HOME/env/miniconda$TRAVIS_PYTHON_VERSION"
if [ ! -d "$src" ]; then
    mkdir -p $HOME/env
    pushd $HOME/env
    
        # Download miniconda packages
        wget http://repo.continuum.io/miniconda/Miniconda-3.16.0-Linux-x86_64.sh -O miniconda.sh;
        # Install libsamplerate
        apt-get source libsamplerate

        # Install both environments
        bash miniconda.sh -b -p $src

        export PATH="$src/bin:$PATH"
        conda_create

        pushd libsamplerate-*
            ./configure --prefix=$src/envs/$ENV_NAME
            make && make install
        popd

        source activate $ENV_NAME

        pip install git+https://github.com/bmcfee/samplerate.git
        pip install python-coveralls

        if [ "$TRAVIS_PYTHON_VERSION" == "2.7" ] ; then
            pip install https://storage.googleapis.com/tensorflow/linux/cpu/tensorflow-0.6.0-cp27-none-linux_x86_64.whl 
        elif [ "$TRAVIS_PYTHON_VERSION" == "3.4" ] ; then
            pip install https://storage.googleapis.com/tensorflow/linux/cpu/tensorflow-0.6.0-cp34-none-linux_x86_64.whl 

        fi

        source deactivate
    popd
else
    echo "Using cached dependencies"
fi
