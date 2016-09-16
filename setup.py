#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

setup(
    name='cmdsignature',
    version='0.0.1',
    description='Command signature',
    long_description=''.join(open('README.md').readlines()),
    keywords='yaml',
    author='Jan Chaloupka',
    author_email='jchaloup@redhat.com',
    url='https://github.com/gofed/cmdsignature',
    license='GPL',
    packages=['cmdsignature'],
    install_requires=open('requirements.txt').read().splitlines()
)
