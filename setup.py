import os
from setuptools import find_packages, setup


def read(fname):
    with open(os.path.join(os.path.dirname(__file__), fname)) as f:
        return f.read()


setup(name='mumble', version='0.0', description='Python library for Mumble.',
      author='Tony Young', author_email='tony@rfw.name',
      url='https://github.com/rfw/python-mumble', license='MIT',
      packages=find_packages(), long_description=read('README.md'),
      classifiers=['Development Status :: 3 - Alpha',
                   'License :: OSI Approved :: MIT License'],
      install_requires=['py3-protobuffers', 'pycryptodome', 'cffi'])
