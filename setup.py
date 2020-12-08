import setuptools
import sys
import versioneer


# NOTE: This file must remain Python 2 compatible for the foreseeable future,
# to ensure that we error out properly for people with outdated setuptools
# and/or pip.
if sys.version_info < (3, 6):
    error = """
Simulacrum does not support Python 2.x, 3.0, 3.1, 3.2, 3.3, 3.4, or 3.5.
Python 3.6 and above is required. Check your Python version like so:

python --version

This may be due to an out-of-date pip. Make sure you have pip >= 9.0.1.
Upgrade pip like so:

pip install --upgrade pip
"""
    sys.exit(error)


classifiers = [
    'Development Status :: 3 - Alpha',
    'Intended Audience :: Science/Research',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.6',
    'Topic :: Scientific/Engineering',
    'License :: OSI Approved :: BSD License'
]

install_requires=['caproto', 'numpy', 'p4p', 'pyzmq']

setuptools.setup(name='simulacrum',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      author='Matt Gibbs (mgibbs@slac.stanford.edu)',
      description='a sans-I/O implementation of the EPICS Channel Access '
                  'protocol',
      packages=['simulacrum'],
      python_requires='>=3.6',
      classifiers=classifiers,
      include_package_data=True,
      package_data={'': ['*.csv']},
      install_requires=install_requires
      )
